from __future__ import annotations

import json
import os
import zipfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st

from fintrace.evaluator import run_frozen_evaluation, run_redteam_evaluation
from fintrace.feedback import record_manual_approval
from fintrace.insights import case_failure_reason, debug_focus, next_action, optimization_insights, review_queue_rows
from fintrace.local_env import load_local_env
from fintrace.pipeline import run_batch
from fintrace.redteam import generate_redteam_batch
from fintrace.showcase import (
    build_case_comparison,
    build_showcase_storyline,
    case_prefix_summary,
    clear_review_widget_state,
    detect_dataset_identity,
    scenario_label,
    suggest_showcase_pairs,
    validate_active_result_consistency,
)


ROOT = Path(__file__).resolve().parent
load_local_env(ROOT)
from fintrace.local_env import warn_missing_config

missing_config = warn_missing_config()

RUNTIME = ROOT / "runtime"
UPLOAD_ROOT = RUNTIME / "uploads"
DEMO_ROOT = RUNTIME / "demo"
EVAL_ROOT = RUNTIME / "eval"
DOCS_ROOT = ROOT / "docs"
SHOWCASE_DATASET = ROOT / "datasets" / "showcase_fintrace_v1"
SHOWCASE_GROUND_TRUTH = SHOWCASE_DATASET / "ground_truth.json"
DEFAULT_LLM_MODE = "deepseek"
DEFAULT_MAX_WORKERS = 4
FINANCE_VISIBLE_ISSUE_TYPES = {"规则命中", "诊断焦点"}

DECISION_LABELS = {
    "APPROVE": "自动通过",
    "APPROVE_WITH_FLEX": "柔性通过",
    "REJECT": "拒绝",
    "MANUAL_REVIEW": "人工复核",
    "ESCALATE_FRAUD": "反舞弊升级",
}
RISK_LABELS = {"LOW": "低", "MEDIUM": "中", "HIGH": "高", "CRITICAL": "严重"}
STATUS_LABELS = {"OK": "正常", "WARN": "预警", "ERROR": "错误"}
RULE_CLASS_LABELS = {"blocking_control": "阻断控制", "contextual_risk_signal": "上下文风险信号"}
ARTIFACT_LABELS = {
    "erp_export": "ERP 导出",
    "spreadsheet": "表格附件",
    "ocr_or_chat_text": "OCR/审批文本",
    "pdf_attachment": "PDF 附件",
    "image_attachment": "图片附件",
    "label_file": "评测标签",
}


st.set_page_config(page_title="FinTrace 费控审核台", layout="wide")

st.markdown(
    """
    <style>
    .block-container {padding-top: 2.5rem; padding-bottom: 2rem; max-width: 1480px;}
    header[data-testid="stHeader"] {background: rgba(255, 255, 255, .96);}
    [data-testid="stMetricValue"] {font-size: 1.42rem;}
    [data-testid="stMetricLabel"] {font-size: .88rem;}
    .fintrace-hero {background: #ffffff; border-bottom: 1px solid #e6eaf0; padding: .35rem 0 .55rem; margin-bottom: .6rem;}
    .fintrace-title {font-size: 1.72rem; font-weight: 780; color: #172033; line-height: 1.25;}
    .fintrace-subtitle {font-size: .94rem; color: #596678; margin-top: .2rem; margin-bottom: .6rem;}
    .section-note {color: #5d6878; font-size: .88rem; margin-bottom: .6rem;}
    .trace-step {border-left: 4px solid #2f80ed; padding: .55rem .75rem; margin: .38rem 0; background: #f7fbff; border-radius: 4px;}
    .trace-warn {border-left-color: #b7791f; background: #fffaf0;}
    .trace-error {border-left-color: #c53030; background: #fff5f5;}
    .small-muted {color: #657282; font-size: .84rem;}
    .decision-pill {display: inline-block; padding: .18rem .48rem; border-radius: 4px; background: #eaf2ff; color: #174ea6; font-weight: 650;}
    .risk-pill {display: inline-block; padding: .18rem .48rem; border-radius: 4px; background: #fff4e5; color: #8a4b00; font-weight: 650;}
    .action-box {border-left: 4px solid #2f80ed; background: #f7fbff; padding: .7rem .85rem; border-radius: 4px; margin: .45rem 0;}
    .danger-box {border-left: 4px solid #c53030; background: #fff5f5; padding: .7rem .85rem; border-radius: 4px; margin: .45rem 0;}
    .explain-card {border: 1px solid #e5eaf1; background: #fbfcfe; border-radius: 6px; padding: .72rem .85rem; min-height: 4.5rem;}
    .explain-card b {color: #1f2a44;}
    .st-keyword-filter {border: 1px solid #e5eaf1; border-radius: 6px; padding: .6rem .85rem; background: #fafbfc;}
    </style>
    """,
    unsafe_allow_html=True,
)


def main() -> None:
    init_state()

    for warning in missing_config:
        st.warning(warning)

    st.markdown(
        """
        <div class="fintrace-hero">
          <div class="fintrace-title">FinTrace 批量费控审核台</div>
          <div class="fintrace-subtitle">查看待处理单据、复核原因和处理建议。点开任意一笔看详情和证据链。</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── 工具栏（横向：导入 + 搜索 + 更多操作） ──────────────────────
    render_toolbar()

    st.divider()

    # ── 概览 ──
    result = st.session_state.get("batch_result")
    if result:
        render_overview(result)
        render_case_table(result)
    else:
        st.info("请点击左上角「加载示例批次」或上传文件开始审核。")


# ═══════════════════════════════════════════════════════════════════
#  状态 / 工具函数
# ═══════════════════════════════════════════════════════════════════

def init_state() -> None:
    st.session_state.setdefault("batch_result", None)
    st.session_state.setdefault("evaluation_report", None)
    st.session_state.setdefault("showcase_evaluation_report", None)
    st.session_state.setdefault("ground_truth_path", "")
    st.session_state.setdefault("deepseek_api_key", "")
    st.session_state.setdefault("active_dataset", "")
    st.session_state.setdefault("active_dataset_manifest", {})
    st.session_state.setdefault("showcase_ground_truth_path", "")
    st.session_state.setdefault("active_result_id", "")
    st.session_state.setdefault("active_source_paths", [])
    st.session_state.setdefault("active_run_started_at", "")
    st.session_state.setdefault("dataset_consistency_warnings", [])
    os.environ.setdefault("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    os.environ.setdefault("DEEPSEEK_MODEL", "deepseek-chat")


def result_key() -> str:
    return str(st.session_state.get("active_result_id") or "no_batch")


def run_showcase_batch(llm_mode: str = "mock", max_workers: int = 4) -> dict:
    batch_id = f"showcase-{uuid4().hex[:8]}"
    return run_batch(
        [str(SHOWCASE_DATASET)],
        output_root=RUNTIME / "batches",
        batch_id=batch_id,
        llm_mode=llm_mode,
        max_workers=max_workers,
    )


def register_batch_result(result: dict, source_paths: list[str], dataset_identity: dict | None = None) -> None:
    identity = dataset_identity or detect_dataset_identity(source_paths, result)
    dataset = identity["dataset"]
    manifest = manifest_for_dataset(dataset)
    ground_truth_path = ground_truth_for_dataset(dataset)
    active_result_id = str(result.get("batch_id") or uuid4().hex[:8])

    st.session_state["batch_result"] = result
    st.session_state["active_dataset"] = dataset
    st.session_state["active_dataset_manifest"] = manifest
    st.session_state["ground_truth_path"] = ground_truth_path
    st.session_state["showcase_ground_truth_path"] = ground_truth_path if dataset == "showcase_fintrace_v1" else ""
    st.session_state["active_result_id"] = active_result_id
    st.session_state["active_source_paths"] = [str(path) for path in source_paths]
    st.session_state["active_run_started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state["dataset_consistency_warnings"] = validate_active_result_consistency(result, dataset)


def manifest_for_dataset(dataset: str) -> dict:
    manifest_paths = {
        "showcase_fintrace_v1": SHOWCASE_DATASET / "dataset_manifest.json",
        "fintrace-redteam-v1": ROOT / "datasets" / "fintrace-redteam-v1" / "dataset_manifest.json",
        "red_attack_v1": ROOT / "datasets" / "red_attack_v1" / "dataset_manifest.json",
    }
    return load_json_if_exists(manifest_paths.get(dataset, Path()))


def ground_truth_for_dataset(dataset: str) -> str:
    ground_truth_paths = {
        "showcase_fintrace_v1": SHOWCASE_GROUND_TRUTH,
        "fintrace-redteam-v1": ROOT / "datasets" / "fintrace-redteam-v1" / "ground_truth.json",
        "red_attack_v1": ROOT / "datasets" / "red_attack_v1" / "ground_truth.json",
    }
    path = ground_truth_paths.get(dataset)
    return str(path) if path and path.exists() else ""


def load_json_if_exists(path: Path) -> dict:
    if not path.exists() or not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_uploaded_files(uploaded_files) -> Path:
    upload_dir = UPLOAD_ROOT / f"upload_{uuid4().hex[:8]}"
    upload_dir.mkdir(parents=True, exist_ok=True)
    for file in uploaded_files:
        target = upload_dir / file.name
        target.write_bytes(file.getbuffer())
        if target.suffix.lower() == ".zip":
            extract_dir = upload_dir / target.stem
            extract_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(target, "r") as zf:
                zf.extractall(extract_dir)
    return upload_dir


def require_batch() -> dict | None:
    result = st.session_state.get("batch_result")
    if not result:
        st.info("请先运行一个批次。")
        return None
    return result


# ═══════════════════════════════════════════════════════════════════
#  工具栏（导入批次 + 搜索 + 更多操作按钮）
# ═══════════════════════════════════════════════════════════════════

def render_toolbar() -> None:
    """横向工具栏：导入批次、搜索全局、评测入口（折叠）。"""
    import_col, search_col, extra_col = st.columns([0.28, 0.44, 0.28], gap="medium")

    with import_col:
        with st.popover("📂 导入批次", use_container_width=True):
            st.markdown('<div class="section-note">上传报销文件或选择示例批次</div>', unsafe_allow_html=True)
            local_path = st.text_input("本地文件/文件夹路径", value="", placeholder="也可用下方上传", key="toolbar_local_path", label_visibility="collapsed")
            uploaded = st.file_uploader(
                "上传文件（ERP 导出、OCR 文本、PDF、图片、ZIP）",
                type=["csv", "xlsx", "xls", "txt", "md", "pdf", "png", "jpg", "jpeg", "zip"],
                accept_multiple_files=True,
                key="toolbar_upload",
                label_visibility="collapsed",
            )
            c1, c2 = st.columns(2)
            showcase_clicked = c1.button("加载示例批次", use_container_width=True, type="primary")
            run_clicked = c2.button("开始审核", use_container_width=True)

    with search_col:
        result = st.session_state.get("batch_result")
        if result:
            rows_df = make_queue_df(result)
            if rows_df is not None and not rows_df.empty:
                keyword = st.text_input("🔍 搜索", placeholder="员工/报销单号/供应商/发票号", key="global_search", label_visibility="collapsed")
                st.session_state["_search_keyword"] = keyword.strip()

    with extra_col:
        c1, c2 = st.columns(2)
        if c1.button("📊 评测", use_container_width=True):
            st.session_state["_show_eval"] = not st.session_state.get("_show_eval", False)
        if c2.button("📖 使用说明", use_container_width=True):
            st.session_state["_show_help"] = not st.session_state.get("_show_help", False)

    # ── 评测面板（折叠） ──
    if st.session_state.get("_show_eval"):
        with st.container(border=True):
            render_eval_panel()

    # ── 使用说明（折叠） ──
    if st.session_state.get("_show_help"):
        with st.container(border=True):
            st.markdown(
                """
                **使用说明**
                1. 点击「导入批次」上传文件或加载示例
                2. 系统自动扫描、匹配附件、执行规则并给出决策
                3. 在案件表格中筛选「人工复核」的单，点开看原因
                4. 确认无误后记录「人工通过」，下次相似场景自动放行
                """
            )

    # ── 执行导入逻辑（在按钮后的位置处理，避免 rerun 混乱） ──
    if showcase_clicked:
        clear_review_widget_state(st.session_state)
        llm_mode = st.session_state.get("_eval_llm_mode", DEFAULT_LLM_MODE)
        max_workers = st.session_state.get("_eval_max_workers", DEFAULT_MAX_WORKERS)
        with st.spinner("正在读取示例批次并运行审核..."):
            batch = run_showcase_batch(llm_mode=llm_mode, max_workers=max_workers)
            register_batch_result(batch, [str(SHOWCASE_DATASET)], {"dataset": "showcase_fintrace_v1", "label": "Showcase 冻结演示集", "expected_prefix": "SHOW"})
        st.rerun()

    if run_clicked:
        clear_review_widget_state(st.session_state)
        source_paths = []
        if local_path.strip():
            source_paths.append(local_path.strip())
        if uploaded:
            upload_dir = save_uploaded_files(uploaded)
            source_paths.append(str(upload_dir))
        if not source_paths:
            st.warning("请至少提供一个本地路径或上传文件。")
        else:
            llm_mode = st.session_state.get("_eval_llm_mode", DEFAULT_LLM_MODE)
            max_workers = st.session_state.get("_eval_max_workers", DEFAULT_MAX_WORKERS)
            with st.spinner("正在归并案件资料并执行批量审核..."):
                batch = run_batch(source_paths, output_root=RUNTIME / "batches", llm_mode=llm_mode, max_workers=max_workers)
                register_batch_result(batch, source_paths)
            st.rerun()


# ═══════════════════════════════════════════════════════════════════
#  概览区
# ═══════════════════════════════════════════════════════════════════

def render_overview(result: dict) -> None:
    insights = optimization_insights(result)
    write_frontend_diagnostics(result, insights)
    summary = insights["summary"]

    cols = st.columns(5)
    cols[0].metric("案件总数", summary["案件总数"])
    cols[1].metric("自动通过", summary["通过"])
    cols[2].metric("人工复核", summary["人工复核"])
    cols[3].metric("拒绝/升级", summary["阻断/升级"])
    cols[4].metric("失败案件", summary["失败案件"])
    st.caption("单笔异常会留痕并进入人工复核，不影响其他单据继续审核。")


# ═══════════════════════════════════════════════════════════════════
#  案件表格
# ═══════════════════════════════════════════════════════════════════

def make_queue_df(result: dict) -> pd.DataFrame | None:
    rows = review_queue_rows(result)
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["数据质量"] = df.apply(review_row_quality, axis=1)
    return df


def render_case_table(result: dict) -> None:
    stream = make_queue_df(result)
    if stream is None or stream.empty:
        st.warning("当前批次没有案件。")
        return

    queue_df = stream.copy()
    st.caption("点击「查看详情」展开处理建议、证据链和技术细节。")
    render_prefix_warnings(result)

    # ── 筛选行 ──
    active_key = result_key()
    search_word = st.session_state.get("_search_keyword", "")

    f1, f2, f3 = st.columns([0.2, 0.2, 0.6])
    decision_filter = f1.multiselect(
        "决策", sorted(queue_df["决策"].dropna().unique()),
        placeholder="全部", key=f"filter_d_{active_key}", label_visibility="collapsed",
    )
    risk_filter = f2.multiselect(
        "风险", sorted(queue_df["风险"].dropna().unique()),
        placeholder="全部风险", key=f"filter_r_{active_key}", label_visibility="collapsed",
    )
    reason_filter = f3.multiselect(
        "复核原因", sorted(queue_df["不通过/复核原因"].dropna().unique()),
        placeholder="复核原因", key=f"filter_reason_{active_key}", label_visibility="collapsed",
    )

    view = queue_df.copy()
    if decision_filter:
        view = view[view["决策"].isin(decision_filter)]
    if risk_filter:
        view = view[view["风险"].isin(risk_filter)]
    if reason_filter:
        view = view[view["不通过/复核原因"].isin(reason_filter)]
    if search_word:
        view = view[view.apply(lambda row: search_word in " ".join(map(str, row.values)), axis=1)]

    st.dataframe(
        view,
        width="stretch",
        hide_index=True,
        column_order=["数据质量", "报销单号", "员工", "费用类型", "金额", "决策", "风险", "不通过/复核原因", "建议动作"],
    )

    # ── 选择一笔看详情 ──
    selected_case = select_case_from_rows(result, view, f"detail_sel_{active_key}")
    if selected_case:
        render_case_detail(selected_case)

    st.divider()

    # ── 案例对比（折叠，原来 Tab3） ──
    with st.expander("📎 案例对比（选两笔对照字段、规则和来源）", expanded=False):
        render_case_comparison(result)


# ═══════════════════════════════════════════════════════════════════
#  案件详情（合并原 Tab1 详情 + Tab2 技术面板）
# ═══════════════════════════════════════════════════════════════════

def render_case_detail(case: dict) -> None:
    decision = case.get("decision", {})
    fields = case.get("parsed_fields", {})
    decision_text = DECISION_LABELS.get(decision.get("decision"), decision.get("decision"))
    risk_text = RISK_LABELS.get(decision.get("risk_level"), decision.get("risk_level"))
    reason = case_failure_reason(case)
    action = next_action(case)
    box_class = "danger-box" if decision.get("decision") in {"REJECT", "ESCALATE_FRAUD"} else "action-box"

    st.markdown("---")
    # 结论卡（财务第一眼看的）
    st.markdown(
        f"""
        <div class="{box_class}">
          <b>{decision_text}</b>｜风险：{risk_text}｜置信度：{decision.get('confidence')}<br/>
          <b>原因：</b>{reason}<br/>
          <b>建议动作：</b>{action}
        </div>
        """,
        unsafe_allow_html=True,
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("金额", fields.get("amount", ""))
    c2.metric("费用类型", fields.get("expense_type", ""))
    c3.metric("供应商", fields.get("vendor", ""))
    c4.metric("发票号", fields.get("invoice_no", ""))
    st.caption(f"命中规则：{rule_id_summary(case)}")

    # ── 原始材料（结论卡下方直接展示，不折叠） ──
    st.markdown("##### 原始材料")
    inv_artifacts = [a for a in case.get("raw_artifacts", []) if "发票" in a.get("artifact_type", "") or "OCR" in str(a.get("path", ""))]
    chat_artifacts = [a for a in case.get("raw_artifacts", []) if "审批" in str(a.get("path", "")) or "chat" in a.get("artifact_type", "")]
    vis_artifacts = [a for a in case.get("raw_artifacts", []) if a.get("artifact_type") in {"image_attachment", "pdf_attachment"}]

    # 发票 OCR 文本
    if inv_artifacts:
        for a in inv_artifacts:
            with st.expander(f"📄 发票 OCR — {Path(a.get('path', '')).name}", expanded=False):
                st.text(a.get("text", "")[:2000])
    elif any("发票OCR" in str(a.get("path", "")) for a in case.get("raw_artifacts", [])):
        pass  # 已覆盖
    else:
        for a in case.get("raw_artifacts", []):
            if a.get("artifact_type") == "erp_row":
                continue
            text = a.get("text", "").strip()
            if text:
                with st.expander(f"📄 {Path(a.get('path', '')).name}", expanded=False):
                    st.text(text[:2000])

    # 审批聊天记录
    if chat_artifacts:
        for a in chat_artifacts:
            with st.expander(f"💬 审批聊天 — {Path(a.get('path', '')).name}", expanded=True):
                st.text(a.get("text", "")[:2000])
    else:
        for a in case.get("raw_artifacts", []):
            if "审批" in str(a.get("path", "")):
                with st.expander(f"💬 审批聊天 — {Path(a.get('path', '')).name}", expanded=True):
                    st.text(a.get("text", "")[:2000])

    # 发票截图（若有）
    if vis_artifacts:
        for a in vis_artifacts:
            p = Path(a.get("path", ""))
            if p.exists():
                st.image(str(p), caption=p.name, width=800)

    # ── 技术细节（折叠） ──
    with st.expander("🔬 查看技术细节（处理过程 / 规则命中 / 字段溯源）", expanded=False):
        tech_tabs = st.tabs(["处理过程", "规则与背景信息", "字段溯源"])

        with tech_tabs[0]:
            st.markdown("##### 处理过程")
            for event in case.get("debug_events", []):
                render_trace_event(event)
            st.markdown("##### 定位建议")
            st.info(debug_recommendation(case))

        with tech_tabs[1]:
            st.markdown("##### 命中控制 / 风险信号")
            hits = case.get("policy_hits", [])
            if hits:
                hit_df = pd.DataFrame(hits)
                if "rule_class" in hit_df:
                    hit_df["rule_class_cn"] = hit_df["rule_class"].map(lambda v: RULE_CLASS_LABELS.get(v, v))
                st.dataframe(hit_df, width="stretch", hide_index=True)
            else:
                st.success("未命中阻断控制或上下文风险信号。")
            st.markdown("##### 未命中规则")
            st.dataframe(pd.DataFrame(missed_rules(hits)), width="stretch", hide_index=True)
            st.markdown("##### 背景信息质量")
            st.json(case.get("context_info", {}).get("context_quality", {}))
            calls = case.get("context_info", {}).get("tool_calls", [])
            if calls:
                st.markdown("##### 背景信息调用（企业本体）")
                st.dataframe(pd.DataFrame(calls), width="stretch", hide_index=True)

        with tech_tabs[2]:
            field_provenance_case_view(case)

    # ── 人工反馈学习 ──
    if decision.get("decision") == "MANUAL_REVIEW":
        with st.expander("📝 人工通过后沉淀为受控例外", expanded=False):
            st.caption("仅对未命中阻断控制、重复票、黑名单、OCR 金额冲突、提示注入等底线风险的边界案例生效。")
            feedback_key = f"{result_key()}_{case.get('case_id')}"
            approver = st.text_input("复核人", value="finance_reviewer", key=f"fb_approver_{feedback_key}")
            feedback_reason = st.text_area("通过理由", value="人工复核确认业务合理。", key=f"fb_reason_{feedback_key}")
            if st.button("记录人工通过并学习", key=f"fb_record_{feedback_key}"):
                fb_result = record_manual_approval(case, approver=approver, reason=feedback_reason)
                if fb_result.get("status") == "recorded":
                    memory = fb_result["memory"]
                    st.success(f"已记录受控例外：{memory['memory_id']}。下次相同模式且金额不超过 {memory['amount_limit']} 元时可自动柔性通过。")
                else:
                    st.warning(fb_result.get("reason", "该案例不适合沉淀为自动通过记忆。"))


def field_provenance_case_view(case: dict) -> None:
    fields = case.get("parsed_fields", {})
    if not fields:
        st.info("该案件没有解析出结构化字段。")
        return
    c1, c2 = st.columns([0.42, 0.58], gap="large")
    with c1:
        field = st.selectbox("选择字段", sorted(fields.keys()), key=f"prov_field_{result_key()}_{case.get('case_id')}")
        provenance = case.get("field_provenance", {}).get(field, [])
        st.json({"字段": field, "当前值": fields.get(field), "来源": provenance})
        source_paths = {src.get("source_path") for src in provenance}
        for artifact in case.get("raw_artifacts", []):
            if artifact.get("path") in source_paths or not provenance:
                with st.expander(Path(artifact.get("path", "")).name):
                    st.text_area(
                        "原始片段",
                        value=(artifact.get("text") or json.dumps(artifact.get("records", []), ensure_ascii=False, indent=2))[:4000],
                        height=180,
                        disabled=True,
                        key=f"prov_txt_{artifact.get('artifact_id')}",
                    )
    with c2:
        st.dataframe(field_rows(case), width="stretch", hide_index=True)


# ═══════════════════════════════════════════════════════════════════
#  案例对比（原来 Tab3，搬到页面底部折叠区）
# ═══════════════════════════════════════════════════════════════════

def render_case_comparison(result: dict) -> None:
    cases = result.get("case_results", [])
    if len(cases) < 2:
        st.info("至少需要两笔案件才能对比。")
        return

    case_by_id = {case.get("case_id"): case for case in cases}
    case_ids = [case.get("case_id") for case in cases if case.get("case_id")]
    ground_truth_path = st.session_state.get("showcase_ground_truth_path") or st.session_state.get("ground_truth_path")
    pairs = suggest_showcase_pairs(result, ground_truth_path)
    active_key = result_key()

    default_left = case_ids[0]
    default_right = case_ids[1]
    if pairs:
        pair_labels = [f"{pair['label']}｜{pair['left_case_id']} vs {pair['right_case_id']}" for pair in pairs]
        selected_label = st.selectbox("推荐对比组合", pair_labels, key=f"cmp_pair_{active_key}")
        selected_pair = pairs[pair_labels.index(selected_label)]
        default_left = selected_pair["left_case_id"]
        default_right = selected_pair["right_case_id"]
        st.caption(selected_pair["reason"])
    else:
        st.caption("当前批次没有标注文件，默认选择前两笔案件进行人工对比。")

    c1, c2 = st.columns(2)
    left_id = c1.selectbox("左侧案件", case_ids, index=case_ids.index(default_left) if default_left in case_ids else 0, key=f"cmp_left_{active_key}")
    right_default_index = case_ids.index(default_right) if default_right in case_ids else min(1, len(case_ids) - 1)
    right_id = c2.selectbox("右侧案件", case_ids, index=right_default_index, key=f"cmp_right_{active_key}")
    if left_id == right_id:
        st.warning("请选择两笔不同案件。")
        return

    comparison = build_case_comparison(case_by_id[left_id], case_by_id[right_id])
    left_summary, right_summary = st.columns(2, gap="large")
    with left_summary:
        render_case_comparison_summary(comparison["left"])
    with right_summary:
        render_case_comparison_summary(comparison["right"])

    st.markdown("##### 核心字段并排")
    st.dataframe(pd.DataFrame(comparison["field_rows"]), width="stretch", hide_index=True)
    st.markdown("##### 命中规则并排")
    st.dataframe(pd.DataFrame(comparison["rule_rows"]), width="stretch", hide_index=True)
    st.markdown("##### 字段来源摘要")
    st.dataframe(pd.DataFrame(comparison["provenance_rows"]), width="stretch", hide_index=True)


def render_case_comparison_summary(summary: dict) -> None:
    st.markdown(f"##### {summary['case_id']}")
    st.markdown(f"**{summary['decision']}**｜风险：{summary['risk']}｜置信度：{summary['confidence']}")
    st.warning(summary["reason"])
    st.info(summary["next_action"])
    refs = summary.get("evidence_refs") or []
    if refs:
        st.caption("证据引用：" + "、".join(map(str, refs)))


# ═══════════════════════════════════════════════════════════════════
#  评测面板（折叠，从原来 showcase_tab 提炼）
# ═══════════════════════════════════════════════════════════════════

def render_eval_panel() -> None:
    st.markdown("#### 评测")
    eval_tabs = st.tabs(["Showcase 回归", "随机红队", "批次指标", "迭代记录"])
    with eval_tabs[0]:
        render_showcase_regression()
    with eval_tabs[1]:
        render_random_eval()
    with eval_tabs[2]:
        render_batch_metrics_panel()
    with eval_tabs[3]:
        render_iteration_log()


def render_showcase_regression() -> None:
    manifest = load_json_if_exists(SHOWCASE_DATASET / "dataset_manifest.json")
    c1, c2, c3 = st.columns(3)
    c1.metric("演示案件", manifest.get("case_count", 6))
    c2.metric("风险场景", manifest.get("scenario_count", 3))
    c3.metric("数据集", manifest.get("dataset", SHOWCASE_DATASET.name))
    if st.button("运行 Showcase 冻结回归", type="primary", key="eval_showcase_run"):
        with st.spinner("正在运行..."):
            st.session_state["showcase_evaluation_report"] = run_frozen_evaluation(
                SHOWCASE_DATASET,
                output_root=EVAL_ROOT / "showcase_frozen",
                batch_id=f"showcase-ui-{uuid4().hex[:8]}",
            )
    report = st.session_state.get("showcase_evaluation_report")
    if report:
        render_evaluation_metrics(report)


def render_random_eval() -> None:
    c1, c2, c3 = st.columns([0.18, 0.18, 0.64])
    n = c1.slider("样本数", min_value=50, max_value=500, value=500, step=50)
    seed = c2.number_input("随机种子", min_value=1, max_value=9999, value=42)
    llm_mode = c3.radio(
        "推理模式", ["mock", "deepseek"], horizontal=True, key="eval_random_llm",
        format_func=lambda v: "本地稳定模型" if v == "mock" else "DeepSeek",
    )
    if st.button("运行测试", type="primary"):
        with st.spinner("正在生成红队样本并评测..."):
            st.session_state["evaluation_report"] = run_redteam_evaluation(EVAL_ROOT, n=n, seed=int(seed), llm_mode=llm_mode)
    report = st.session_state.get("evaluation_report")
    if report:
        render_evaluation_metrics(report)


def render_evaluation_metrics(report: dict) -> None:
    metrics = report["metrics"]
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("决策准确率", f"{metrics['decision_accuracy']:.1%}")
    m2.metric("硬违规 Precision", f"{metrics['hard_precision']:.1%}")
    m3.metric("硬违规 Recall", f"{metrics['hard_recall']:.1%}")
    m4.metric("硬违规 F1", f"{metrics['hard_f1']:.1%}")
    m5.metric("字段准确率", f"{metrics['field_accuracy']:.1%}")
    st.caption(f"批次：{report['batch_id']} | 产物目录：{report['work_dir']}")
    target_df = pd.DataFrame([{"目标": k, "是否达成": "✅ 达成" if v else "❌ 未达成"} for k, v in metrics.get("target_status", {}).items()])
    st.dataframe(target_df, width="stretch", hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**场景分布**")
        scenario = metrics.get("scenario_breakdown", {})
        st.dataframe(pd.DataFrame([{"场景": scenario_label(k), **v} for k, v in scenario.items()]), width="stretch", hide_index=True)
    with c2:
        st.markdown("**错误类型**")
        errors = metrics.get("error_type_counts", {})
        if errors:
            st.dataframe(pd.DataFrame({"错误类型": list(errors.keys()), "数量": list(errors.values())}), width="stretch", hide_index=True)
        else:
            st.success("本轮没有 case 级错误。")
    if metrics["case_errors"]:
        st.markdown("**错误 Drill-down**")
        st.dataframe(pd.DataFrame(metrics["case_errors"]), width="stretch", hide_index=True)


def render_batch_metrics_panel() -> None:
    result = require_batch()
    if not result:
        return
    render_aggregate_metrics(result)
    metrics = result.get("batch_metrics", {})
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**文件类型分布**")
        file_df = pd.DataFrame(
            {"文件类型": [ARTIFACT_LABELS.get(k, k) for k in metrics.get("file_type_distribution", {})],
             "数量": list(metrics.get("file_type_distribution", {}).values())}
        )
        st.dataframe(file_df, width="stretch", hide_index=True)
    with c2:
        st.markdown("**节点事件与失败**")
        node_df = pd.DataFrame({"节点": list(metrics.get("node_event_counts", {}).keys()), "事件数": list(metrics.get("node_event_counts", {}).values())})
        st.dataframe(node_df, width="stretch", hide_index=True)
        st.metric("节点失败数", metrics.get("node_failure_count", 0))
        st.metric("失败案件数", metrics.get("case_failed_count", 0))
    st.markdown("**Top 错误源**")
    render_error_registry(result)


def render_aggregate_metrics(result: dict) -> None:
    metrics = result.get("batch_metrics", {})
    decisions = metrics.get("decision_counts", {})
    case_count = metrics.get("case_count", 0) or 1
    cols = st.columns(7)
    cols[0].metric("案件数", metrics.get("case_count", 0))
    cols[1].metric("成功案件", metrics.get("case_success_count", metrics.get("case_count", 0)))
    cols[2].metric("失败案件", metrics.get("case_failed_count", 0))
    cols[3].metric("通过率", f"{(decisions.get('APPROVE', 0) + decisions.get('APPROVE_WITH_FLEX', 0)) / case_count:.1%}")
    cols[4].metric("人工复核率", f"{decisions.get('MANUAL_REVIEW', 0) / case_count:.1%}")
    cols[5].metric("拒绝/升级率", f"{(decisions.get('REJECT', 0) + decisions.get('ESCALATE_FRAUD', 0)) / case_count:.1%}")
    cols[6].metric("平均节点耗时", f"{metrics.get('avg_node_latency_ms', 0)} ms")
    chart_df = pd.DataFrame({"决策": [DECISION_LABELS.get(k, k) for k in decisions], "数量": list(decisions.values())})
    if not chart_df.empty:
        st.bar_chart(chart_df, x="决策", y="数量", color="#2f80ed")


def render_iteration_log() -> None:
    log_path = DOCS_ROOT / "ITERATION_LOG.md"
    if log_path.exists():
        st.markdown(log_path.read_text(encoding="utf-8"))
    else:
        st.info("尚未生成迭代记录。")
    st.divider()
    st.markdown("**本地评测报告**")
    reports = sorted(RUNTIME.rglob("evaluation_report_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:8]
    if not reports:
        st.caption("暂无评测报告。")
        return
    rows = []
    for path in reports:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            metrics = data.get("metrics", {})
            rows.append({
                "报告": str(path),
                "样本数": metrics.get("total_cases"),
                "决策准确率": metrics.get("decision_accuracy"),
                "硬违规Recall": metrics.get("hard_recall"),
                "字段准确率": metrics.get("field_accuracy"),
                "错误数": len(metrics.get("case_errors", [])),
            })
        except json.JSONDecodeError:
            continue
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


# ═══════════════════════════════════════════════════════════════════
#  通用 UI 组件
# ═══════════════════════════════════════════════════════════════════

def render_prefix_warnings(result: dict) -> None:
    prefixes = case_prefix_summary(result)
    if len(prefixes) > 1:
        st.warning("当前批次数据异常，请重新加载示例批次或重新运行审核。")
    if st.session_state.get("active_dataset") == "showcase_fintrace_v1":
        non_show = {prefix: count for prefix, count in prefixes.items() if prefix != "SHOW"}
        if non_show:
            st.error("当前批次数据异常，请重新加载示例批次或重新运行审核。")


def review_row_quality(row: pd.Series) -> str:
    required_fields = ["报销单号", "员工", "费用类型", "金额"]
    missing = []
    for field in required_fields:
        value = row.get(field)
        if value is None or str(value).strip().lower() in {"", "none", "nan", "nat"}:
            missing.append(field)
    return "字段缺失/解析异常" if missing else "字段完整"


def rule_id_summary(case: dict) -> str:
    rule_ids = [str(hit.get("rule_id")) for hit in case.get("policy_hits", []) if hit.get("rule_id")]
    return "、".join(rule_ids) if rule_ids else "未命中规则"


def field_source_summary(case: dict) -> str:
    provenance = case.get("field_provenance", {})
    parts = []
    for field, label in [("amount", "金额"), ("invoice_no", "发票号"), ("expense_type", "费用类型"), ("vendor", "供应商")]:
        sources = provenance.get(field, [])
        if not sources:
            continue
        first = sources[0]
        parts.append(f"{label}:{first.get('artifact_id')} {first.get('locator') or ''}".strip())
    return "；".join(parts[:4]) if parts else "暂无字段来源摘要"


def invoice_attachment_summary(case: dict) -> str:
    names = []
    for artifact in case.get("raw_artifacts", []):
        if artifact.get("artifact_type") not in {"image_attachment", "pdf_attachment"}:
            continue
        path = Path(artifact.get("path", ""))
        names.append(path.name)
    return "；".join(names[:4]) if names else "暂无可视化票据附件"


def select_case_from_rows(result: dict, rows: pd.DataFrame, key: str) -> dict | None:
    if rows.empty:
        return None
    options = []
    for _, row in rows.iterrows():
        options.append(f"{row['报销单号']}｜{row['员工']}｜{row['决策']}｜{row['金额']}｜{row['case_id']}")
    selected = st.selectbox("点开一笔单看具体原因", options, key=key)
    case_id = selected.rsplit("｜", 1)[-1]
    return next((case for case in result.get("case_results", []) if case.get("case_id") == case_id), None)


def render_trace_event(event: dict) -> None:
    status = event.get("status", "OK")
    css = "trace-step"
    if status == "WARN":
        css += " trace-warn"
    elif status == "ERROR":
        css += " trace-error"
    details = event.get("details", {})
    st.markdown(
        f"""
        <div class="{css}">
          <b>{event.get('node_name')}</b>
          <span class="small-muted"> | {STATUS_LABELS.get(status, status)} | {event.get('latency_ms')} ms | 置信度 {event.get('confidence')}</span><br/>
          <span class="small-muted">下一路由：{event.get('next_route')} | 输出：{', '.join(map(str, event.get('output_refs', [])))}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if details or event.get("errors"):
        with st.expander(f"查看 {event.get('node_name')} 节点载荷"):
            st.json({"details": details, "errors": event.get("errors", [])})


def field_rows(case: dict) -> pd.DataFrame:
    rows = []
    provenance = case.get("field_provenance", {})
    fields = case.get("parsed_fields", {})
    for field, value in fields.items():
        sources = provenance.get(field, [])
        if sources:
            for source in sources:
                rows.append({
                    "字段": field,
                    "值": value,
                    "来源artifact": source.get("artifact_id"),
                    "定位": source.get("locator"),
                    "置信度": source.get("confidence"),
                    "抽取方式": source.get("extraction_method"),
                })
        else:
            rows.append({"字段": field, "值": value, "来源artifact": "batch_feature", "定位": "", "置信度": "", "抽取方式": "batch_enrichment"})
    return pd.DataFrame(rows)


def render_error_registry(result: dict) -> None:
    registry = result.get("error_registry", {})
    if not registry:
        st.success("暂无解析或节点错误。")
        return
    for category, errs in registry.items():
        with st.expander(f"{category} | {len(errs)} 条"):
            st.dataframe(pd.DataFrame(errs), width="stretch", hide_index=True)


def missed_rules(hits: list[dict]) -> list[dict[str, str]]:
    hit_ids = {h.get("rule_id") for h in hits}
    all_rules = {
        "R001_MISSING_ORIGINAL": ("缺少发票原件", "blocking_control"),
        "R002_DUPLICATE_INVOICE": ("重复发票号/哈希", "blocking_control"),
        "R003_SPLIT_INVOICE": ("疑似拆票", "contextual_risk_signal"),
        "R004_ABSOLUTE_LIMIT": ("金额超过静态标准", "contextual_risk_signal"),
        "R005_VENDOR_BLACKLIST": ("供应商黑名单", "blocking_control"),
        "R006_CROSS_PERIOD": ("跨期报销", "contextual_risk_signal"),
        "R007_SIMILAR_INVOICE_NO": ("高度相似发票号", "contextual_risk_signal"),
        "R008_OCR_AMOUNT_CONFLICT": ("OCR 金额冲突", "contextual_risk_signal"),
        "R009_CHAT_PROMPT_INJECTION": ("审批聊天越权诱导", "contextual_risk_signal"),
        "R010_APPROVAL_INCOMPLETE": ("审批状态未完成", "contextual_risk_signal"),
        "R011_ABNORMAL_AMOUNT": ("金额异常", "contextual_risk_signal"),
        "R012_TIME_SPACE_CONFLICT": ("时空冲突", "contextual_risk_signal"),
        "R013_PURPOSE_ATTACHMENT_MISMATCH": ("事由与附件不一致", "contextual_risk_signal"),
    }
    return [
        {"rule_id": rid, "规则": name, "规则分类": RULE_CLASS_LABELS.get(rc, rc), "状态": "未命中"}
        for rid, (name, rc) in all_rules.items() if rid not in hit_ids
    ]


def debug_recommendation(case: dict) -> str:
    errors = case.get("errors", [])
    hits = case.get("policy_hits", [])
    reasoning = case.get("reasoning_trace", {})
    llm_meta = reasoning.get("llm_meta", {})
    if errors:
        return "优先检查字段溯源：该案件存在字段缺失或字段冲突。"
    if hits:
        blocking = [h for h in hits if h.get("rule_class") == "blocking_control"]
        if blocking:
            return "优先检查阻断控制：这类规则可直接拒绝或升级，辅助分析不允许覆盖。"
        return "优先检查上下文风险信号：这些不是硬拒绝，但需要业务背景或人工复核。"
    if llm_meta.get("status") == "fallback":
        return "优先检查模型辅助分析：外部服务未返回可用结构化结果，系统已使用本地稳定判断。"
    guardrail = reasoning.get("llm_guardrail_status", {})
    if guardrail.get("status") and guardrail.get("status") != "local_baseline":
        return "优先检查辅助分析校验：系统记录了模型建议是否被采纳、回退或转人工。"
    return "当前处理过程完整，可从背景信息调用和最终审计摘要确认放行原因。"


def write_frontend_diagnostics(result: dict, insights: dict) -> None:
    hidden_rows = [
        row for row in insights.get("top_issues", [])
        if row.get("类型") not in FINANCE_VISIBLE_ISSUE_TYPES
    ]
    diagnostics_dir = RUNTIME / "diagnostics"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# FinTrace 前端内部诊断",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 批次：{result.get('batch_id', '')}",
        f"- 产物目录：{result.get('work_dir', '')}",
        "",
        "## 主界面已隐藏的开发诊断",
    ]
    if hidden_rows:
        lines.extend(["", "| 类型 | 问题 | 数量 | 内部建议 |", "|---|---|---:|---|"])
        for row in hidden_rows:
            lines.append(f"| {row.get('类型', '')} | {row.get('问题', '')} | {row.get('数量', '')} | {row.get('优化建议', '')} |")
    else:
        lines.append("")
        lines.append("暂无需要从财务主界面隐藏的开发诊断。")

    error_registry = result.get("error_registry", {})
    lines.extend(["", "## Error Registry", ""])
    if error_registry:
        for category, errs in error_registry.items():
            lines.append(f"- {category}：{len(errs)} 条")
    else:
        lines.append("- 无错误记录。")

    lines.extend([
        "",
        "## 查看方式",
        "",
        "- 财务主界面只展示业务风险和待处理单据。",
        "- 字段来源、规则命中和处理过程在展开详情中可查看。",
        "- 本文件用于开发复盘，不面向外部展示。",
    ])
    (diagnostics_dir / "latest_frontend_diagnostics.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
