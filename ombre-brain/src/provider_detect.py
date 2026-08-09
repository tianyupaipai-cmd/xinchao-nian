"""
========================================
provider_detect.py — LLM/embedding provider 识别与模型名归一化
========================================

dehydrator.py（压缩用 LLM）和 embedding_engine.py（向量化）各自独立写过
一遍「这是不是 Gemini 端点」「模型名该不该带 models/ 前缀」的判断逻辑，
写法和覆盖面有细微差异，是 2026-06-30 修复 embedding 模型名 bug（裸名 vs
models/ 前缀混淆）的根源之一。这里把判断逻辑收敛成一份，两边共用，以后
端点判断只用改一处。

不做什么：
- 不处理 AQ.* key 的 api_format 自动切换决策（那条逻辑只有 dehydrator.py
  在用，且与「是否是 Gemini 端点」判断耦合较深，暂不抽出，避免过度抽象）
========================================
"""

from __future__ import annotations


def is_gemini_native_host(base_url: str) -> bool:
    """base_url 是否指向 Google 的 generativelanguage.googleapis.com 域名。

    只看域名，不关心是 native REST 还是 OpenAI-compat 子路径——用于
    「这把 key/这个 base_url 是不是在跟 Google 打交道」这一级别的判断
    （如 dehydrator.py 的 AQ.* key 自动切换检测）。
    """
    return "generativelanguage.googleapis.com" in (base_url or "")


def is_gemini_openai_compat_endpoint(base_url: str) -> bool:
    """base_url 是否是 Gemini 的 OpenAI 兼容端点（.../v1beta/openai/）。

    区别于原生 REST 端点（.../v1beta/models/...:generateContent）：
    OpenAI-compat 端点要求裸模型名（"gemini-embedding-001"），原生 REST
    要求带 "models/" 资源前缀（"models/gemini-embedding-001"）。混淆两者
    是 OB-E001（"unexpected model name format"）的根因。
    """
    base_url_norm = (base_url or "").rstrip("/")
    return is_gemini_native_host(base_url_norm) and "/openai" in base_url_norm


def normalize_model_for_endpoint(model: str, base_url: str) -> str:
    """根据端点类型决定模型名要不要带 "models/" 前缀。

    - Gemini OpenAI-compat 端点：剥掉 "models/" 前缀（裸名）
    - 其他端点（含 Gemini 原生 REST、第三方 OpenAI 兼容代理）：原样保留
      （原生 REST 自己的调用点会在拼 URL 时单独剥前缀，因为它的资源路径
      格式要求与 OpenAI-compat 不同，不能在这里统一处理）
    """
    model = (model or "").strip()
    if is_gemini_openai_compat_endpoint(base_url):
        return model.removeprefix("models/").strip()
    return model


def strip_native_resource_prefix(model: str) -> str:
    """剥掉 Gemini 原生 REST 资源路径前缀，得到裸模型 id。

    原生 REST 端点（.../v1beta/models/{model}:generateContent 或
    :embedContent）的 URL 本身就包含 "models/" 段，所以传入的 model 不能
    重复带前缀，否则拼出 "models/models/xxx" 这种坏 URL。
    """
    return (model or "").strip().removeprefix("models/").strip()
