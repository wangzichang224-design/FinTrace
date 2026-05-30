from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st

from fintrace.evaluator import run_redteam_evaluation
from fintrace.feedback import record_manual_approval
from fintrace.insights import case_failure_reason, debug_focus, next_action, optimization_insights, review_queue_rows
from fintrace.pipeline import run_batch
from fintrace.redteam import generate_redteam_batch


ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
UPLOAD_ROOT = RUNTIME / "uploads"
DEMO_ROOT = RUNTIME / "demo"
EVAL_ROOT = RUNTIME / "eval"
DOCS_ROOT = ROOT / "docs"

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


st.set_page_config(page_title="FinTrace 中文费控 Agent", layout="wide")

st.markdown(
    """
    <style>
    .block-container {padding-top: 3.2rem; padding-bottom: 2rem; max-width: 1480px;}
    header[data-testid="stHeader"] {background: rgba(255, 255, 255, .96);}
    [data-testid="stMetricValue"] {font-size: 1.42rem;}
    [data-testid="stMetricLabel"] {font-size: .88rem;}
    .fintrace-hero {background: #ffffff; border-bottom: 1px solid #e6eaf0; padding: .45rem 0 .75rem; margin-bottom: .8rem;}
    .fintrace-title {font-size: 1.82rem; font-weight: 780; color: #172033; line-height: 1.25;}
    .fintrace-subtitle {font-size: .96rem; color: #596678; margin-top: .25rem; margin-bottom: .85rem;}
    .section-note {color: #5d6878; font-size: .88rem; margin-bottom: .7rem;}
    .trace-step {border-left: 4px solid #2f80ed; padding: .55rem .75rem; margin: .38rem 0; background: #f7fbff; border-radius: 4px;}
    .trace-warn {border-left-color: #b7791f; background: #fffaf0;}
    .trace-error {border-left-color: #c53030; background: #fff5f5;}
    .small-muted {color: #657282; font-size: .84rem;}
    .decision-pill {display: inline-block; padding: .18rem .48rem; border-radius: 4px; background: #eaf2ff; color: #174ea6; font-weight: 650;}
    .risk-pill {display: inline-block; padding: .18rem .48rem; border-radius: 4px; background: #fff4e5; color: #8a4b00; font-weight: 650;}
    .action-box {border-left: 4px solid #2f80ed; background: #f7fbff; padding: .7rem .85rem; border-radius: 4px; margin: .45rem 0;}
    .danger-box {border-left: 4px solid #c53030; background: #fff5f5; padding: .7rem .85rem; border-radius: 4px; margin: .45rem 0;}
    .explain-card {border: 1px solid #e5eaf1; background: #fbfcfe; border-radius: 6px; padding: .72rem .85rem; min-height: 6.2rem;}
    .explain-card b {color: #1f2a44;}
    div[data-testid="stTabs"] button p {font-size: .95rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


def main() -> None:
    init_state()
    render_sidebar()
    st.markdown(
        """
        <div class="fintrace-hero">
          <div class="fintrace-title">FinTrace 批量费控审核台</div>
          <div class="fintrace-subtitle">给财务同事日常批量初审使用：先看哪些单要处理、为什么、下一步怎么做；需要排查细节时再点“查原因”。</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.info("当前定位：先做批量初审和可解释复核。DeepSeek 只辅助写审计摘要，最终风控边界仍由本地规则和门控兜底。")

    tabs = st.tabs(["批量审核", "查原因", "测试结果"])
    with tabs[0]:
        finance_review_tab()
    with tabs[1]:
        diagnostics_optimization_tab()
    with tabs[2]:
        showcase_tab()


def init_state() -> None:
    st.session_state.setdefault("batch_result", None)
    st.session_state.setdefault("evaluation_report", None)
    st.session_state.setdefault("ground_truth_path", "")
    st.session_state.setdefault("deepseek_api_key", "")


def render_sidebar() -> None:
    st.sidebar.header("运行配置")
    st.sidebar.caption("DeepSeek Key 仅保存在当前 Streamlit 会话和进程环境变量中，不会写入项目文件。")
    llm_key = st.sidebar.text_input("DeepSeek API Key", type="password", value=st.session_state.get("deepseek_api_key", ""))
    if llm_key:
        st.session_state["deepseek_api_key"] = llm_key
        os.environ["DEEPSEEK_API_KEY"] = llm_key
        st.sidebar.success("DeepSeek 凭证已注入当前会话")
    elif os.getenv("DEEPSEEK_API_KEY"):
        st.sidebar.success("已检测到环境变量 DEEPSEEK_API_KEY")
    else:
        os.environ.pop("DEEPSEEK_API_KEY", None)
        st.sidebar.info("未配置 Key 时，DeepSeek 模式会自动回退到本地模型")
    base_url = st.sidebar.text_input("DeepSeek Base URL", value=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"))
    model = st.sidebar.text_input("DeepSeek 模型", value=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"))
    os.environ["DEEPSEEK_BASE_URL"] = base_url.strip() or "https://api.deepseek.com/v1"
    os.environ["DEEPSEEK_MODEL"] = model.strip() or "deepseek-chat"


def finance_review_tab() -> None:
    st.subheader("批量审核")
    st.markdown(
        '<div class="section-note">上传或输入文件夹，查看哪些单能过、哪些要复核、为什么要复核，以及下一步具体动作。</div>',
        unsafe_allow_html=True,
    )
    left, right = st.columns([0.34, 0.66], gap="large")
    with left:
        st.markdown("#### 导入批次")
        local_path = st.text_input("本地文件/文件夹路径", value="", placeholder=r"D:\03_AI_Projects\FinTrace\runtime\demo\demo_xxxx", key="finance_local_path")
        uploaded = st.file_uploader(
            "上传 ERP 导出、OCR 文本、PDF/图片附件或 ZIP 包",
            type=["csv", "xlsx", "xls", "txt", "md", "pdf", "png", "jpg", "jpeg", "zip"],
            accept_multiple_files=True,
            key="finance_upload",
        )
        with st.expander("高级设置", expanded=False):
            llm_mode = st.radio(
                "推理模式",
                ["mock", "deepseek"],
                horizontal=True,
                key="finance_llm_mode",
                format_func=lambda v: "本地稳定模型" if v == "mock" else "DeepSeek 结构化推理",
            )
            max_workers = st.slider("并发处理线程数", min_value=1, max_value=8, value=4, key="finance_workers")
        run_clicked = st.button("运行批量审核", width="stretch", type="primary", key="finance_run")
        demo_clicked = st.button("生成演示批次", width="stretch", key="finance_demo")

    with right:
        result = st.session_state.get("batch_result")
        if result:
            render_finance_overview(result)
        else:
            st.info("还没有运行批次。录屏展示时可以先点“生成演示批次”，系统会生成一批高仿真 ERP 报销和附件。")

    if demo_clicked:
        demo_dir = DEMO_ROOT / f"demo_{uuid4().hex[:8]}"
        with st.spinner("正在生成高仿真 ERP 批次并运行审核..."):
            info = generate_redteam_batch(demo_dir, n=80, seed=42)
            st.session_state["batch_result"] = run_batch([info["source_dir"]], output_root=RUNTIME / "batches", llm_mode=llm_mode, max_workers=max_workers)
            st.session_state["ground_truth_path"] = info["ground_truth_path"]
        st.rerun()

    if run_clicked:
        source_paths = []
        if local_path.strip():
            source_paths.append(local_path.strip())
        if uploaded:
            upload_dir = save_uploaded_files(uploaded)
            source_paths.append(str(upload_dir))
        if not source_paths:
            st.warning("请至少提供一个本地路径或上传文件。")
            return
        with st.spinner("正在扫描 manifest、归并案件包并执行批量审核..."):
            st.session_state["batch_result"] = run_batch(source_paths, output_root=RUNTIME / "batches", llm_mode=llm_mode, max_workers=max_workers)
        st.rerun()

    result = st.session_state.get("batch_result")
    if not result:
        return

    st.divider()
    st.markdown("#### 待处理案件池")
    queue_df = pd.DataFrame(review_queue_rows(result))
    if queue_df.empty:
        st.warning("当前批次没有案件。")
        return

    f1, f2, f3, f4 = st.columns([0.2, 0.2, 0.22, 0.38])
    decision_filter = f1.multiselect("决策", sorted(queue_df["决策"].dropna().unique()), key="finance_decision_filter")
    risk_filter = f2.multiselect("风险", sorted(queue_df["风险"].dropna().unique()), key="finance_risk_filter")
    focus_filter = f3.multiselect("问题类型", sorted(queue_df["诊断焦点"].dropna().unique()), key="finance_focus_filter")
    keyword = f4.text_input("搜索员工/单号/供应商/发票号", key="finance_keyword")

    view = queue_df.copy()
    if decision_filter:
        view = view[view["决策"].isin(decision_filter)]
    if risk_filter:
        view = view[view["风险"].isin(risk_filter)]
    if focus_filter:
        view = view[view["诊断焦点"].isin(focus_filter)]
    if keyword.strip():
        needle = keyword.strip()
        view = view[view.apply(lambda row: needle in " ".join(map(str, row.values)), axis=1)]

    st.dataframe(
        view,
        width="stretch",
        hide_index=True,
        column_order=["报销单号", "员工", "费用类型", "金额", "决策", "风险", "不通过/复核原因", "建议动作"],
    )

    selected_case = select_case_from_rows(result, view, "finance_case_detail")
    if selected_case:
        render_finance_case_detail(selected_case)


def render_finance_overview(result: dict) -> None:
    insights = optimization_insights(result)
    summary = insights["summary"]
    metrics = result.get("batch_metrics", {})
    cols = st.columns(5)
    cols[0].metric("案件总数", summary["案件总数"])
    cols[1].metric("自动通过", summary["通过"])
    cols[2].metric("人工复核", summary["人工复核"])
    cols[3].metric("拒绝/升级", summary["阻断/升级"])
    cols[4].metric("失败案件", summary["失败案件"])
    st.caption(metrics.get("partial_failure_policy", "批处理中单案失败会留痕并转人工，不回滚整个批次。"))
    if insights["top_issues"]:
        top = pd.DataFrame(insights["top_issues"]).head(5)
        st.markdown("#### 本批次最值得先看的问题")
        st.dataframe(top, width="stretch", hide_index=True)


def select_case_from_rows(result: dict, rows: pd.DataFrame, key: str) -> dict | None:
    if rows.empty:
        return None
    options = []
    for _, row in rows.iterrows():
        options.append(f"{row['报销单号']}｜{row['员工']}｜{row['决策']}｜{row['金额']}｜{row['case_id']}")
    selected = st.selectbox("点开一笔单看具体原因", options, key=key)
    case_id = selected.rsplit("｜", 1)[-1]
    return next((case for case in result.get("case_results", []) if case.get("case_id") == case_id), None)


def render_finance_case_detail(case: dict) -> None:
    st.markdown("#### 当前案件处理建议")
    decision = case.get("decision", {})
    fields = case.get("parsed_fields", {})
    decision_text = DECISION_LABELS.get(decision.get("decision"), decision.get("decision"))
    risk_text = RISK_LABELS.get(decision.get("risk_level"), decision.get("risk_level"))
    reason = case_failure_reason(case)
    action = next_action(case)
    box_class = "danger-box" if decision.get("decision") in {"REJECT", "ESCALATE_FRAUD"} else "action-box"
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
    with st.expander("查看审计摘要和证据引用", expanded=False):
        trace = case.get("reasoning_trace", {})
        st.write(trace.get("reasoning_summary") or decision.get("reason") or "暂无审计摘要。")
        st.json(
            {
                "证据引用": decision.get("evidence_refs", []),
                "人工复核原因": decision.get("manual_review_reason", ""),
                "门控状态": decision.get("guardrail_status", ""),
                "诊断焦点": debug_focus(case),
            }
        )
    if decision.get("decision") == "MANUAL_REVIEW":
        with st.expander("人工通过后沉淀为受控例外", expanded=False):
            st.caption("仅对未命中阻断控制、重复票、黑名单、OCR 金额冲突、提示注入等底线风险的边界案例生效。")
            approver = st.text_input("复核人", value="finance_reviewer", key=f"feedback_approver_{case.get('case_id')}")
            feedback_reason = st.text_area("通过理由", value="人工复核确认业务合理。", key=f"feedback_reason_{case.get('case_id')}")
            if st.button("记录人工通过并学习", key=f"feedback_record_{case.get('case_id')}"):
                result = record_manual_approval(case, approver=approver, reason=feedback_reason)
                if result.get("status") == "recorded":
                    memory = result["memory"]
                    st.success(f"已记录受控例外：{memory['memory_id']}。下次相同模式且金额不超过 {memory['amount_limit']} 元时可自动柔性通过。")
                else:
                    st.warning(result.get("reason", "该案例不适合沉淀为自动通过记忆。"))


def diagnostics_optimization_tab() -> None:
    result = require_batch()
    if not result:
        return
    st.subheader("查原因")
    st.markdown(
        '<div class="section-note">这里不是日常审核主页面，而是用来点开一笔单，看证据、规则、字段来源和运行链路。</div>',
        unsafe_allow_html=True,
    )
    c0, c1, c2 = st.columns(3)
    c0.markdown('<div class="explain-card"><b>字段溯源</b><br/>这笔金额、城市、发票号是从哪个 ERP 行、OCR 文本或审批聊天里抽出来的。</div>', unsafe_allow_html=True)
    c1.markdown('<div class="explain-card"><b>规则命中</b><br/>系统为什么认为它有风险，例如拆单、时空冲突、审批未完成或附件不一致。</div>', unsafe_allow_html=True)
    c2.markdown('<div class="explain-card"><b>运行链路</b><br/>如果结果不准，用来定位错在文件解析、字段抽取、规则、本体还是 DeepSeek 门控。</div>', unsafe_allow_html=True)
    insights = optimization_insights(result)
    s = insights["summary"]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("需处理案件", s["需处理案件"])
    c2.metric("人工复核", s["人工复核"])
    c3.metric("拒绝/升级", s["阻断/升级"])
    c4.metric("失败案件", s["失败案件"])
    c5.metric("通过案件", s["通过"])

    st.markdown("#### 本批次问题汇总")
    if insights["top_issues"]:
        st.dataframe(pd.DataFrame(insights["top_issues"]), width="stretch", hide_index=True)
    else:
        st.success("本批次暂未发现需要优先优化的问题。")

    st.markdown("#### 查询具体案件")
    rows = pd.DataFrame(review_queue_rows(result))
    query = st.text_input("输入员工、报销单号、供应商、规则 ID、错误类型或诊断焦点", key="diagnostic_query")
    if query.strip():
        needle = query.strip()
        rows = rows[rows.apply(lambda row: needle in " ".join(map(str, row.values)), axis=1)]
    st.dataframe(
        rows,
        width="stretch",
        hide_index=True,
        column_order=["报销单号", "员工", "费用类型", "金额", "决策", "风险", "不通过/复核原因", "建议动作"],
    )

    case = select_case_from_rows(result, rows, "diagnostic_case_selector")
    if not case:
        return

    detail_tabs = st.tabs(["不通过原因", "运行链路", "规则与本体", "字段溯源"])
    with detail_tabs[0]:
        st.markdown("#### 不通过 / 复核原因")
        st.warning(case_failure_reason(case))
        st.info(f"建议动作：{next_action(case)}")
        st.markdown("#### 定位建议")
        st.write(debug_recommendation(case))
        st.markdown("#### 结构化审计底稿")
        st.json(case.get("reasoning_trace", {}))
    with detail_tabs[1]:
        st.markdown("#### 节点运行过程")
        for event in case.get("debug_events", []):
            render_trace_event(event)
    with detail_tabs[2]:
        st.markdown("#### 命中控制 / 风险信号")
        hits = case.get("policy_hits", [])
        if hits:
            hit_df = pd.DataFrame(hits)
            if "rule_class" in hit_df:
                hit_df["rule_class_cn"] = hit_df["rule_class"].map(lambda v: RULE_CLASS_LABELS.get(v, v))
            st.dataframe(hit_df, width="stretch", hide_index=True)
        else:
            st.success("未命中阻断控制或上下文风险信号。")
        st.markdown("#### 企业本体质量")
        st.json(case.get("context_info", {}).get("context_quality", {}))
        calls = case.get("context_info", {}).get("tool_calls", [])
        if calls:
            st.markdown("#### 本体工具调用")
            st.dataframe(pd.DataFrame(calls), width="stretch", hide_index=True)
    with detail_tabs[3]:
        field_provenance_case_view(case)


def field_provenance_case_view(case: dict) -> None:
    fields = case.get("parsed_fields", {})
    if not fields:
        st.info("该案件没有解析出结构化字段。")
        return
    c1, c2 = st.columns([0.42, 0.58], gap="large")
    with c1:
        field = st.selectbox("选择字段", sorted(fields.keys()), key=f"diagnostic_field_{case.get('case_id')}")
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
                        key=f"diag_field_{artifact.get('artifact_id')}",
                    )
    with c2:
        st.dataframe(field_rows(case), width="stretch", hide_index=True)


def showcase_tab() -> None:
    st.subheader("测试结果")
    st.markdown('<div class="section-note">这里主要给开发和展示使用：看红队测试集、回归指标和迭代记录。日常财务审核只看“批量审核”。</div>', unsafe_allow_html=True)
    tabs = st.tabs(["跑测试", "批次指标", "迭代记录"])
    with tabs[0]:
        evaluation_tab()
    with tabs[1]:
        batch_metrics_tab()
    with tabs[2]:
        iteration_tab()


def batch_processing_tab() -> None:
    st.subheader("批量处理台")
    st.markdown('<div class="section-note">支持多文件上传、ZIP 包、文件夹路径输入，模拟企业 ERP 批量审单。</div>', unsafe_allow_html=True)
    left, right = st.columns([0.42, 0.58], gap="large")
    with left:
        local_path = st.text_input("本地文件/文件夹路径", value="", placeholder=r"D:\03_AI_Projects\FinTrace\runtime\demo\demo_xxxx")
        uploaded = st.file_uploader(
            "上传 ERP 导出、OCR 文本、PDF/图片附件或 ZIP 包",
            type=["csv", "xlsx", "xls", "txt", "md", "pdf", "png", "jpg", "jpeg", "zip"],
            accept_multiple_files=True,
        )
        llm_mode = st.radio("推理模式", ["mock", "deepseek"], horizontal=True, format_func=lambda v: "本地稳定模型" if v == "mock" else "DeepSeek 结构化推理")
        max_workers = st.slider("并发处理线程数", min_value=1, max_value=8, value=4)
        c1, c2 = st.columns(2)
        run_clicked = c1.button("运行批量审查", width="stretch", type="primary")
        demo_clicked = c2.button("生成高仿真样本并运行", width="stretch")

    with right:
        result = st.session_state.get("batch_result")
        if result:
            render_batch_metrics(result)
            st.caption("本次批处理产物目录")
            st.code(result.get("work_dir", ""), language="text")
        else:
            st.info("还没有运行批次。建议先点击“生成高仿真样本并运行”，可直接得到适合录屏的 80 笔批量案件。")

    if demo_clicked:
        demo_dir = DEMO_ROOT / f"demo_{uuid4().hex[:8]}"
        with st.spinner("正在生成高仿真 ERP 批次，并运行 FinTrace 双层状态机..."):
            info = generate_redteam_batch(demo_dir, n=80, seed=42)
            st.session_state["batch_result"] = run_batch([info["source_dir"]], output_root=RUNTIME / "batches", llm_mode=llm_mode, max_workers=max_workers)
            st.session_state["ground_truth_path"] = info["ground_truth_path"]
        st.rerun()

    if run_clicked:
        source_paths = []
        if local_path.strip():
            source_paths.append(local_path.strip())
        if uploaded:
            upload_dir = save_uploaded_files(uploaded)
            source_paths.append(str(upload_dir))
        if not source_paths:
            st.warning("请至少提供一个本地路径或上传文件。")
            return
        with st.spinner("正在扫描 manifest、归并案件包、并行执行 CaseGraph..."):
            st.session_state["batch_result"] = run_batch(source_paths, output_root=RUNTIME / "batches", llm_mode=llm_mode, max_workers=max_workers)
        st.rerun()

    result = st.session_state.get("batch_result")
    if result:
        st.divider()
        st.markdown("#### 批量 Manifest")
        manifest_df = pd.DataFrame(result.get("manifest", []))
        if not manifest_df.empty:
            manifest_df["artifact_type"] = manifest_df["artifact_type"].map(lambda v: ARTIFACT_LABELS.get(v, v))
        st.dataframe(manifest_df, width="stretch", hide_index=True)
        st.markdown("#### 错误定位台")
        render_error_registry(result)


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


def render_batch_metrics(result: dict) -> None:
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
    if metrics.get("partial_failure_policy"):
        st.caption(f"部分失败策略：{metrics.get('partial_failure_policy')}")
    chart_df = pd.DataFrame({"决策": [DECISION_LABELS.get(k, k) for k in decisions], "数量": list(decisions.values())})
    if not chart_df.empty:
        st.bar_chart(chart_df, x="决策", y="数量", color="#2f80ed")


def case_explorer_tab() -> None:
    result = require_batch()
    if not result:
        return
    st.subheader("案件列表")
    cases = flatten_cases(result)
    df = pd.DataFrame(cases)
    if df.empty:
        st.warning("当前批次没有案件。")
        return

    f1, f2, f3, f4 = st.columns(4)
    decision_filter = f1.multiselect("决策结果", sorted(df["decision_cn"].dropna().unique()))
    risk_filter = f2.multiselect("风险等级", sorted(df["risk_level_cn"].dropna().unique()))
    employee_filter = f3.multiselect("员工", sorted(df["employee_name"].dropna().unique()))
    error_filter = f4.multiselect("错误类型", sorted({e for row in df["error_types"] for e in row}))
    view = df.copy()
    if decision_filter:
        view = view[view["decision_cn"].isin(decision_filter)]
    if risk_filter:
        view = view[view["risk_level_cn"].isin(risk_filter)]
    if employee_filter:
        view = view[view["employee_name"].isin(employee_filter)]
    if error_filter:
        view = view[view["error_types"].apply(lambda values: bool(set(values) & set(error_filter)))]

    st.dataframe(
        view.drop(columns=["error_types", "decision", "risk_level"]),
        width="stretch",
        hide_index=True,
        column_order=["case_id", "decision_cn", "risk_level_cn", "amount", "expense_type", "employee_name", "department", "vendor", "invoice_no", "confidence", "guardrail_status", "reason"],
    )


def audit_probe_tab() -> None:
    result = require_batch()
    if not result:
        return
    st.subheader("审计探针")
    case = select_case(result)
    if not case:
        return

    decision = case.get("decision", {})
    st.markdown(
        f"""<span class="decision-pill">{DECISION_LABELS.get(decision.get('decision'), decision.get('decision'))}</span>
        <span class="risk-pill">风险：{RISK_LABELS.get(decision.get('risk_level'), decision.get('risk_level'))}</span>
        <span class="small-muted"> 置信度：{decision.get('confidence')}</span>""",
        unsafe_allow_html=True,
    )
    st.caption(decision.get("reason", ""))
    if decision.get("guardrail_status"):
        st.caption(f"门控状态：{decision.get('guardrail_status')} | 人工复核原因：{decision.get('manual_review_reason', '')}")

    left, right = st.columns([0.44, 0.56], gap="large")
    with left:
        st.markdown("#### 原始材料")
        for artifact in case.get("raw_artifacts", []):
            title = f"{artifact.get('artifact_id')} | {Path(artifact.get('path', '')).name}"
            with st.expander(title, expanded=artifact.get("artifact_type") == "erp_row"):
                st.caption(artifact.get("path", ""))
                if artifact.get("records"):
                    st.json(artifact.get("records", [])[0])
                text = artifact.get("text") or ""
                if text:
                    st.text_area("抽取文本", value=text[:5000], height=220, disabled=True, key=f"text_{artifact.get('artifact_id')}")
                else:
                    st.caption("该附件暂未抽取出文本。若为扫描 PDF/图片，可先导入 OCR 文本或后续接入本地 OCR。")

    with right:
        st.markdown("#### 逻辑链路")
        for event in case.get("debug_events", []):
            render_trace_event(event)
        st.markdown("#### 结构化审计底稿")
        st.json(case.get("reasoning_trace", {}))


def field_provenance_tab() -> None:
    result = require_batch()
    if not result:
        return
    st.subheader("字段溯源视图")
    case = select_case(result, key="field_case_selector")
    if not case:
        return
    fields = case.get("parsed_fields", {})
    provenance = case.get("field_provenance", {})
    c1, c2 = st.columns([0.42, 0.58], gap="large")
    with c1:
        st.markdown("#### 字段选择")
        field = st.selectbox("选择要定位的字段", sorted(fields.keys()))
        st.json({"字段": field, "当前值": fields.get(field), "来源": provenance.get(field, [])})
        st.markdown("#### 原始片段")
        sources = provenance.get(field, [])
        source_paths = {src.get("source_path") for src in sources}
        for artifact in case.get("raw_artifacts", []):
            if artifact.get("path") in source_paths or not sources:
                with st.expander(Path(artifact.get("path", "")).name):
                    st.text_area("文本片段", value=(artifact.get("text") or json.dumps(artifact.get("records", []), ensure_ascii=False, indent=2))[:4000], height=180, disabled=True, key=f"field_{artifact.get('artifact_id')}")
    with c2:
        st.markdown("#### 结构化字段")
        st.dataframe(field_rows(case), width="stretch", hide_index=True)


def rule_debugger_tab() -> None:
    result = require_batch()
    if not result:
        return
    st.subheader("规则调试台")
    case = select_case(result, key="rule_case_selector")
    if not case:
        return
    fields = case.get("parsed_fields", {})
    hits = case.get("policy_hits", [])
    c1, c2 = st.columns([0.44, 0.56], gap="large")
    with c1:
        st.markdown("#### 输入字段快照")
        st.json(fields)
        st.markdown("#### 建议定位")
        st.info(debug_recommendation(case))
    with c2:
        st.markdown("#### 命中控制 / 风险信号")
        if hits:
            hit_df = pd.DataFrame(hits)
            if "rule_class" in hit_df:
                hit_df["rule_class_cn"] = hit_df["rule_class"].map(lambda v: RULE_CLASS_LABELS.get(v, v))
            st.dataframe(hit_df, width="stretch", hide_index=True)
        else:
            st.success("未命中阻断控制或上下文风险信号。")
        st.markdown("#### 未命中规则")
        missed = missed_rules(hits)
        st.dataframe(pd.DataFrame(missed), width="stretch", hide_index=True)
        st.markdown("#### 企业本体工具调用")
        calls = case.get("context_info", {}).get("tool_calls", [])
        if calls:
            st.dataframe(pd.DataFrame(calls), width="stretch", hide_index=True)
            st.markdown("#### 本体冷启动质量")
            st.json(case.get("context_info", {}).get("context_quality", {}))
        else:
            st.caption("该案件被阻断控制直接拦截，未进入本体工具调用。")


def batch_metrics_tab() -> None:
    result = require_batch()
    if not result:
        return
    st.subheader("批次指标")
    render_batch_metrics(result)
    metrics = result.get("batch_metrics", {})
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.markdown("#### 文件类型分布")
        file_df = pd.DataFrame(
            {"文件类型": [ARTIFACT_LABELS.get(k, k) for k in metrics.get("file_type_distribution", {})], "数量": list(metrics.get("file_type_distribution", {}).values())}
        )
        st.dataframe(file_df, width="stretch", hide_index=True)
    with c2:
        st.markdown("#### 节点事件与失败")
        node_df = pd.DataFrame({"节点": list(metrics.get("node_event_counts", {}).keys()), "事件数": list(metrics.get("node_event_counts", {}).values())})
        st.dataframe(node_df, width="stretch", hide_index=True)
        st.metric("节点失败数", metrics.get("node_failure_count", 0))
        st.metric("失败案件数", metrics.get("case_failed_count", 0))
        st.caption(metrics.get("partial_failure_policy", "部分失败策略未记录"))
    st.markdown("#### Top 错误源")
    render_error_registry(result)


def evaluation_tab() -> None:
    st.subheader("跑测试")
    st.markdown('<div class="section-note">这里用固定或随机样本检查系统有没有退步。日常财务人员不用看这一页，录屏或开发回归时使用。</div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([0.22, 0.22, 0.56])
    n = c1.slider("样本数", min_value=50, max_value=500, value=500, step=50)
    seed = c2.number_input("随机种子", min_value=1, max_value=9999, value=42)
    llm_mode = c3.radio("推理模式", ["mock", "deepseek"], horizontal=True, key="eval_llm_mode", format_func=lambda v: "本地稳定模型" if v == "mock" else "DeepSeek 结构化推理")
    if st.button("运行测试", type="primary"):
        with st.spinner("正在生成红队批量样本、运行 FinTrace、计算 Precision / Recall / F1..."):
            st.session_state["evaluation_report"] = run_redteam_evaluation(EVAL_ROOT, n=n, seed=int(seed), llm_mode=llm_mode)
    report = st.session_state.get("evaluation_report")
    if not report:
        st.info("点击运行后，可以看到准确率、召回率、字段抽取准确率和错误案件。")
        return
    render_evaluation_report(report)


def iteration_tab() -> None:
    st.subheader("迭代记录")
    log_path = DOCS_ROOT / "ITERATION_LOG.md"
    if log_path.exists():
        st.markdown(log_path.read_text(encoding="utf-8"))
    else:
        st.info("尚未生成迭代记录。完成测试和复测后会写入 docs/ITERATION_LOG.md。")
    st.divider()
    st.markdown("#### 本地评测报告")
    reports = sorted(RUNTIME.rglob("evaluation_report_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:8]
    if not reports:
        st.caption("暂无评测报告。")
        return
    rows = []
    for path in reports:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            metrics = data.get("metrics", {})
            rows.append(
                {
                    "报告": str(path),
                    "样本数": metrics.get("total_cases"),
                    "决策准确率": metrics.get("decision_accuracy"),
                    "硬违规Recall": metrics.get("hard_recall"),
                    "字段准确率": metrics.get("field_accuracy"),
                    "错误数": len(metrics.get("case_errors", [])),
                }
            )
        except json.JSONDecodeError:
            continue
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def render_evaluation_report(report: dict) -> None:
    metrics = report["metrics"]
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("决策准确率", f"{metrics['decision_accuracy']:.1%}")
    m2.metric("硬违规 Precision", f"{metrics['hard_precision']:.1%}")
    m3.metric("硬违规 Recall", f"{metrics['hard_recall']:.1%}")
    m4.metric("硬违规 F1", f"{metrics['hard_f1']:.1%}")
    m5.metric("字段准确率", f"{metrics['field_accuracy']:.1%}")
    st.caption(f"批次：{report['batch_id']} | 产物目录：{report['work_dir']}")
    target_df = pd.DataFrame([{"目标": k, "是否达成": "达成" if v else "未达成"} for k, v in metrics.get("target_status", {}).items()])
    st.dataframe(target_df, width="stretch", hide_index=True)
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.markdown("#### 场景分布")
        scenario = metrics.get("scenario_breakdown", {})
        st.dataframe(pd.DataFrame([{"场景": k, **v} for k, v in scenario.items()]), width="stretch", hide_index=True)
    with c2:
        st.markdown("#### 错误类型")
        errors = metrics.get("error_type_counts", {})
        if errors:
            st.dataframe(pd.DataFrame({"错误类型": list(errors.keys()), "数量": list(errors.values())}), width="stretch", hide_index=True)
        else:
            st.success("本轮没有 case 级错误。")
    if metrics["case_errors"]:
        st.markdown("#### 错误 Drill-down")
        st.dataframe(pd.DataFrame(metrics["case_errors"]), width="stretch", hide_index=True)


def require_batch() -> dict | None:
    result = st.session_state.get("batch_result")
    if not result:
        st.info("请先在“批量审核”运行一个批次。")
        return None
    return result


def flatten_cases(result: dict) -> list[dict]:
    rows = []
    for case in result.get("case_results", []):
        fields = case.get("parsed_fields", {})
        decision = case.get("decision", {})
        error_types = sorted({err.get("category", "未知错误") for err in case.get("errors", [])})
        rows.append(
            {
                "case_id": case.get("case_id"),
                "decision": decision.get("decision"),
                "decision_cn": DECISION_LABELS.get(decision.get("decision"), decision.get("decision")),
                "risk_level": decision.get("risk_level"),
                "risk_level_cn": RISK_LABELS.get(decision.get("risk_level"), decision.get("risk_level")),
                "confidence": decision.get("confidence"),
                "reason": decision.get("reason"),
                "guardrail_status": decision.get("guardrail_status"),
                "employee_id": fields.get("employee_id"),
                "employee_name": fields.get("employee_name"),
                "department": fields.get("department"),
                "amount": fields.get("amount"),
                "expense_type": fields.get("expense_type"),
                "vendor": fields.get("vendor"),
                "invoice_no": fields.get("invoice_no"),
                "error_types": error_types,
            }
        )
    return rows


def select_case(result: dict, key: str = "case_selector") -> dict | None:
    cases = result.get("case_results", [])
    if not cases:
        st.warning("当前批次没有案件。")
        return None
    case_ids = [c["case_id"] for c in cases]
    selected = st.selectbox("选择案件", case_ids, key=key)
    return next((c for c in cases if c["case_id"] == selected), None)


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
                rows.append(
                    {
                        "字段": field,
                        "值": value,
                        "来源artifact": source.get("artifact_id"),
                        "定位": source.get("locator"),
                        "置信度": source.get("confidence"),
                        "抽取方式": source.get("extraction_method"),
                    }
                )
        else:
            rows.append({"字段": field, "值": value, "来源artifact": "batch_feature", "定位": "", "置信度": "", "抽取方式": "batch_enrichment"})
    return pd.DataFrame(rows)


def render_error_registry(result: dict) -> None:
    registry = result.get("error_registry", {})
    if not registry:
        st.success("暂无解析或节点错误。")
        return
    for category, rows in registry.items():
        with st.expander(f"{category} | {len(rows)} 条"):
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


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
        {"rule_id": rid, "规则": name, "规则分类": RULE_CLASS_LABELS.get(rule_class, rule_class), "状态": "未命中"}
        for rid, (name, rule_class) in all_rules.items()
        if rid not in hit_ids
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
            return "优先检查阻断控制：这类规则可直接拒绝或升级，LLM 不允许覆盖。"
        return "优先检查上下文风险信号：这些不是硬拒绝，但需要业务背景或人工复核。"
    if llm_meta.get("status") == "fallback":
        return "优先检查 LLM 调用：DeepSeek 未返回可用 JSON，系统已回退到本地模型。"
    guardrail = reasoning.get("llm_guardrail_status", {})
    if guardrail.get("status") and guardrail.get("status") != "local_baseline":
        return "优先检查 LLM 门控：系统记录了 DeepSeek 是否被采纳、回退或转人工。"
    return "当前链路完整，可从本体工具调用和最终审计底稿确认放行原因。"


if __name__ == "__main__":
    main()
