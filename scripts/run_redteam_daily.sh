#!/usr/bin/env bash
# ==============================================================================
# 观察层 Red-Team 压力测试「手动补跑 / 调试」脚本
#
# ⚠️ 重要：正式触发已由事件驱动挂钩接管（os2_report 写盘成功后自动触发，
#    backend/os_layers/redteam_trigger.py），本脚本【不要】接入 cron / 定时任务，
#    仅用于手动补跑当日缺失记录或调试编排器。
#
# 触发时机：每日收盘且 os2_report 生成后（建议 17:30 - 18:30）
#
# 注意：本系统每日研报真实产物为 HTML（output/memo_${TODAY}.html），
#       编排器会在读取时自动剥离 HTML 标签，无需手动转换。
#       若你的部署环境 os2_report 输出为其他路径，请修改下方 INPUT_FILE。
# ==============================================================================

set -euo pipefail

# 1. 基础路径与日期配置
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TODAY="$(date +%Y-%m-%d)"

INPUT_FILE="${PROJECT_ROOT}/output/memo_${TODAY}.html"
OUTPUT_DIR="${PROJECT_ROOT}/output/redteam_records"
LOG_DIR="${PROJECT_ROOT}/logs/redteam"
OUTPUT_FILE="${OUTPUT_DIR}/redteam_record_${TODAY}.md"
LOG_FILE="${LOG_DIR}/redteam_${TODAY}.log"

# 2. 目录初始化
mkdir -p "${OUTPUT_DIR}" "${LOG_DIR}"

# 3. 日志与终端双向输出函数
log() {
    local level="$1"
    shift
    local msg="$*"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [${level}] ${msg}" | tee -a "${LOG_FILE}"
}

log "INFO" "==================== 启动 Red-Team 压力测试 ===================="

# 4. 环境变量与鉴权检查
if [[ -z "${LLM_API_KEY:-}" && -z "${OPENAI_API_KEY:-}" ]]; then
    log "ERROR" "未检测到 LLM_API_KEY 或 OPENAI_API_KEY，脚本终止。"
    exit 1
fi

export LLM_BASE_URL="${LLM_BASE_URL:-https://api.openai.com/v1}"
export LLM_MODEL="${LLM_MODEL:-gpt-4o}"

# 5. 输入文件存在性检查
if [[ ! -f "${INPUT_FILE}" ]]; then
    # 若带日期的文件不存在，尝试检查默认固定路径
    ALT_INPUT="${PROJECT_ROOT}/output/memo.html"
    if [[ -f "${ALT_INPUT}" ]]; then
        INPUT_FILE="${ALT_INPUT}"
        log "WARN" "未找到带日期的研报，回退使用通用文件: ${INPUT_FILE}"
    else
        log "ERROR" "未找到今日投研报告文件: ${INPUT_FILE}，跳过本次压力测试。"
        exit 0
    fi
fi

# 6. 执行 Python 审查流水线
log "INFO" "输入报告: ${INPUT_FILE}"
log "INFO" "输出目标: ${OUTPUT_FILE}"
log "INFO" "调用模型: ${LLM_MODEL} @ ${LLM_BASE_URL}"

python3 "${PROJECT_ROOT}/backend/os_layers/redteam_pressure_test.py" \
    --input "${INPUT_FILE}" \
    --output "${OUTPUT_FILE}" >> "${LOG_FILE}" 2>&1

EXIT_CODE=$?

if [[ ${EXIT_CODE} -eq 0 ]]; then
    log "INFO" "Red-Team 压力测试执行完毕，记录已归档至: ${OUTPUT_FILE}"
else
    log "ERROR" "Red-Team 脚本执行异常，退出码: ${EXIT_CODE}，请检查日志: ${LOG_FILE}"
    exit ${EXIT_CODE}
fi

log "INFO" "==================== 流程正常结束 ===================="
