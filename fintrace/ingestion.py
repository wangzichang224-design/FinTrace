from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .schemas import CasePackage, RawArtifact
from .storage import ensure_dir


ERP_EXTENSIONS = {".csv", ".xlsx", ".xls"}
TEXT_EXTENSIONS = {".txt", ".md", ".json"}
PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
SUPPORTED_EXTENSIONS = ERP_EXTENSIONS | TEXT_EXTENSIONS | PDF_EXTENSIONS | IMAGE_EXTENSIONS | {".zip"}


@dataclass
class ManifestItem:
    artifact_id: str
    path: str
    filename: str
    extension: str
    artifact_type: str
    size_bytes: int
    sha256: str
    status: str = "ready"
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def prepare_sources(source_paths: list[str], work_dir: Path) -> list[Path]:
    """Expand directories and zip files into concrete files."""
    ensure_dir(work_dir)
    concrete: list[Path] = []
    for raw in source_paths:
        path = Path(raw).expanduser()
        if not path.exists():
            continue
        if path.is_dir():
            concrete.extend([p for p in path.rglob("*") if p.is_file()])
            continue
        if path.suffix.lower() == ".zip":
            target = ensure_dir(work_dir / "unzipped" / path.stem)
            with zipfile.ZipFile(path, "r") as zf:
                zf.extractall(target)
            concrete.extend([p for p in target.rglob("*") if p.is_file()])
            continue
        concrete.append(path)
    return [p for p in concrete if p.suffix.lower() in SUPPORTED_EXTENSIONS and p.suffix.lower() != ".zip"]


def scan_manifest(files: list[Path]) -> list[ManifestItem]:
    items: list[ManifestItem] = []
    for idx, path in enumerate(sorted(files, key=lambda p: str(p).lower())):
        ext = path.suffix.lower()
        artifact_type = classify_artifact(path)
        try:
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            status = "ready"
            error = ""
            size = len(data)
        except OSError as exc:
            digest = ""
            status = "error"
            error = str(exc)
            size = 0
        items.append(
            ManifestItem(
                artifact_id=f"A{idx + 1:05d}",
                path=str(path),
                filename=path.name,
                extension=ext,
                artifact_type=artifact_type,
                size_bytes=size,
                sha256=digest,
                status=status,
                error=error,
            )
        )
    return items


def classify_artifact(path: Path) -> str:
    ext = path.suffix.lower()
    lower_name = path.name.lower()
    if lower_name in {"ground_truth.json", "labels.json"} or "ground_truth" in lower_name:
        return "label_file"
    if ext in ERP_EXTENSIONS and any(token in lower_name for token in ("erp", "expense", "reimburse", "报销", "费控")):
        return "erp_export"
    if ext in ERP_EXTENSIONS:
        return "spreadsheet"
    if ext in TEXT_EXTENSIONS:
        return "ocr_or_chat_text"
    if ext in PDF_EXTENSIONS:
        return "pdf_attachment"
    if ext in IMAGE_EXTENSIONS:
        return "image_attachment"
    return "unknown"


def assemble_cases(batch_id: str, manifest: list[dict[str, Any]]) -> list[CasePackage]:
    """Create case packages from ERP rows and matched heterogeneous attachments."""
    erp_artifacts: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    attachment_artifacts: list[RawArtifact] = []

    for item in manifest:
        path = Path(item["path"])
        if item["status"] != "ready":
            continue
        if item["artifact_type"] == "label_file":
            continue
        if item["artifact_type"] in {"erp_export", "spreadsheet"}:
            rows = load_table_rows(path)
            if rows:
                erp_artifacts.append((item, rows))
            else:
                attachment_artifacts.append(load_attachment(item))
        else:
            attachment_artifacts.append(load_attachment(item))

    cases: list[CasePackage] = []
    if erp_artifacts:
        for item, rows in erp_artifacts:
            for row_idx, row in enumerate(rows, start=1):
                reimbursement_id = str(row.get("reimbursement_id") or row.get("claim_id") or "").strip()
                case_id = normalize_case_id(reimbursement_id) or f"C{len(cases) + 1:05d}"
                artifact = RawArtifact(
                    artifact_id=f"{item['artifact_id']}-R{row_idx:04d}",
                    path=item["path"],
                    artifact_type="erp_row",
                    case_id=case_id,
                    records=[row],
                    metadata={"row_number": row_idx, "source_artifact_id": item["artifact_id"]},
                )
                matched = match_attachments(case_id, row, attachment_artifacts)
                cases.append(CasePackage(case_id=case_id, batch_id=batch_id, raw_artifacts=[artifact] + matched))
    else:
        for idx, artifact in enumerate(attachment_artifacts, start=1):
            case_id = normalize_case_id(extract_case_hint(artifact)) or f"C{idx:05d}"
            artifact.case_id = case_id
            cases.append(CasePackage(case_id=case_id, batch_id=batch_id, raw_artifacts=[artifact]))

    enrich_batch_features(cases)
    return cases


def load_table_rows(path: Path) -> list[dict[str, Any]]:
    try:
        if path.suffix.lower() == ".csv":
            df = read_csv_best_effort(path)
        else:
            df = pd.read_excel(path)
    except Exception:
        return []
    if df.empty:
        return []
    df = df.where(pd.notnull(df), None)
    rows = df.to_dict(orient="records")
    known_cols = {
        "reimbursement_id",
        "claim_id",
        "amount",
        "employee_id",
        "invoice_no",
        "expense_type",
        "报销单号",
        "单据编号",
        "金额",
        "价税合计",
        "员工ID",
        "员工编号",
        "发票号",
        "发票号码",
        "费用类型",
        "报销类型",
    }
    if known_cols & {str(col) for col in df.columns}:
        return rows
    return []


def read_csv_best_effort(path: Path) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    return pd.read_csv(path)


def load_attachment(item: dict[str, Any]) -> RawArtifact:
    path = Path(item["path"])
    text = ""
    metadata: dict[str, Any] = {"source_artifact_id": item["artifact_id"], "sha256": item.get("sha256", "")}
    if path.suffix.lower() in TEXT_EXTENSIONS:
        text = read_text_best_effort(path)
        metadata["extraction_method"] = "text_file"
    elif path.suffix.lower() in PDF_EXTENSIONS:
        text = extract_pdf_text(path)
        metadata["extraction_method"] = "pypdf" if text else "pdf_no_text"
    elif path.suffix.lower() in IMAGE_EXTENSIONS:
        text = extract_image_text_optional(path)
        metadata["extraction_method"] = "local_ocr" if text else "ocr_unavailable"
    return RawArtifact(
        artifact_id=item["artifact_id"],
        path=str(path),
        artifact_type=item["artifact_type"],
        text=text,
        metadata=metadata,
    )


def read_text_best_effort(path: Path) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(errors="ignore")


def extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages = []
        for page_idx, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"[page={page_idx}]\n{text}")
        return "\n\n".join(pages)
    except Exception:
        return ""


def extract_image_text_optional(path: Path) -> str:
    """Try optional OCR packages without making OCR a required dependency."""
    try:
        import pytesseract
        from PIL import Image

        return pytesseract.image_to_string(Image.open(path), lang="chi_sim+eng")
    except Exception:
        return ""


def match_attachments(case_id: str, row: dict[str, Any], attachments: list[RawArtifact]) -> list[RawArtifact]:
    keys = build_attachment_match_keys(case_id, row)
    matched: list[RawArtifact] = []
    for artifact in attachments:
        haystack = f"{Path(artifact.path).name} {artifact.text[:3000]}"
        score, matched_keys = attachment_match_score(haystack, keys)
        if score >= 60:
            copied = RawArtifact(**artifact.to_dict())
            copied.case_id = case_id
            copied.metadata["match_score"] = score
            copied.metadata["matched_keys"] = matched_keys
            matched.append(copied)
    return matched


def build_attachment_match_keys(case_id: str, row: dict[str, Any]) -> list[tuple[str, str, int]]:
    raw_keys = [
        ("case_id", case_id, 100),
        ("reimbursement_id", row.get("reimbursement_id") or row.get("claim_id"), 100),
        ("invoice_no", row.get("invoice_no"), 70),
        ("invoice_hash", row.get("invoice_hash"), 90),
    ]
    keys: list[tuple[str, str, int]] = []
    seen: set[str] = set()
    for name, value, score in raw_keys:
        token = str(value or "").strip()
        if not token or token.lower() == "none":
            continue
        normalized = normalize_match_token(token)
        if normalized and normalized not in seen:
            keys.append((name, token, score))
            seen.add(normalized)
    return keys


def attachment_match_score(haystack: str, keys: list[tuple[str, str, int]]) -> tuple[int, list[str]]:
    score = 0
    matched: list[str] = []
    for key_name, raw_token, weight in keys:
        if contains_exact_token(haystack, raw_token):
            score += weight
            matched.append(key_name)
    return score, matched


def contains_exact_token(haystack: str, token: str) -> bool:
    normalized_haystack = normalize_match_token(haystack)
    normalized_token = normalize_match_token(token)
    if not normalized_token:
        return False
    pattern = rf"(?<![A-Za-z0-9]){re.escape(normalized_token)}(?![A-Za-z0-9])"
    return re.search(pattern, normalized_haystack) is not None


def normalize_match_token(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", " ", str(value).lower()).strip()


def enrich_batch_features(cases: list[CasePackage]) -> None:
    invoice_groups: dict[str, list[CasePackage]] = {}
    split_groups: dict[str, list[CasePackage]] = {}
    similar_invoice_groups: dict[str, list[CasePackage]] = {}

    for case in cases:
        row = first_record(case)
        invoice_key = str(row.get("invoice_hash") or row.get("invoice_no") or "").strip().lower()
        if invoice_key:
            invoice_groups.setdefault(invoice_key, []).append(case)
        split_key = "|".join(
            [
                str(row.get("employee_id") or "").strip().lower(),
                str(row.get("vendor") or "").strip().lower(),
                str(row.get("expense_type") or "").strip().lower(),
                str(row.get("expense_date") or "")[:10],
            ]
        )
        if split_key.strip("|"):
            split_groups.setdefault(split_key, []).append(case)
        similar_key = "|".join(
            [
                str(row.get("employee_id") or "").strip().lower(),
                str(row.get("vendor") or "").strip().lower(),
                str(row.get("expense_date") or "")[:10],
            ]
        )
        if similar_key.strip("|"):
            similar_invoice_groups.setdefault(similar_key, []).append(case)

    for group in invoice_groups.values():
        for case in group:
            case.batch_features["invoice_duplicate_count"] = len(group)
    for group in split_groups.values():
        total = sum(safe_float(first_record(case).get("amount")) for case in group)
        for case in group:
            case.batch_features["split_group_count"] = len(group)
            case.batch_features["split_group_total"] = round(total, 2)
    for group in similar_invoice_groups.values():
        mark_similar_invoice_cases(group)


def mark_similar_invoice_cases(group: list[CasePackage]) -> None:
    for idx, case in enumerate(group):
        invoice_no = str(first_record(case).get("invoice_no") or "").strip()
        peers: list[str] = []
        for other_idx, other in enumerate(group):
            if idx == other_idx:
                continue
            other_no = str(first_record(other).get("invoice_no") or "").strip()
            if invoice_no and other_no and invoice_no != other_no and invoice_distance(invoice_no, other_no) <= 1:
                peers.append(other.case_id)
        if peers:
            case.batch_features["similar_invoice_count"] = len(peers) + 1
            case.batch_features["similar_invoice_peers"] = peers


def invoice_distance(left: str, right: str) -> int:
    if len(left) != len(right):
        return max(len(left), len(right))
    return sum(1 for a, b in zip(left, right) if a != b)


def first_record(case: CasePackage) -> dict[str, Any]:
    for artifact in case.raw_artifacts:
        if artifact.records:
            return artifact.records[0]
    return {}


def normalize_case_id(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value).strip())
    return value.strip("-")


def extract_case_hint(artifact: RawArtifact) -> str:
    haystack = f"{Path(artifact.path).stem} {artifact.text[:500]}"
    patterns = [
        r"(?:reimbursement_id|claim_id|报销单号|单据编号)[:：\s]+([A-Za-z0-9_-]+)",
        r"(FT-\d{4,})",
        r"(RMB-\d{4,})",
    ]
    for pattern in patterns:
        hit = re.search(pattern, haystack, re.I)
        if hit:
            return hit.group(1)
    return Path(artifact.path).stem


def safe_float(value: Any) -> float:
    try:
        return float(str(value).replace(",", "").replace("￥", "").replace("¥", "").strip())
    except (TypeError, ValueError):
        return 0.0
