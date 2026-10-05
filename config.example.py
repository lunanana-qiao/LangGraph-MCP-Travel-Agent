# 复制本文件为 config.py 并填入真实密钥（config.py 已被 .gitignore 排除，不会被提交）
# Copy this file to config.py and fill in your real keys.

# LLM Configuration（豆包 / 火山引擎）
LLM_CONFIG = {
    "api_key": "your_doubao_api_key_here",
    "model_name": "doubao-seed-2-0-lite-260215",
    "base_url": "https://ark.cn-beijing.volces.com/api/v3",
    "temperature": 0.7,
    "max_tokens": 8192,
}

# System Configuration
SYSTEM_CONFIG = {
    "enable_llm": True,
    "log_level": "INFO",
    "max_retries": 3,
    "timeout": 60,
}

# RAG 知识库：嵌入模型（本地路径）
RAG_CONFIG = {
    "embedding_model": "data/models/bge-small-zh-v1.5",
}

# 连接与可用性：重试、熔断、健康检查
RESILIENCE_CONFIG = {
    "max_retries": 3,
    "retry_base_delay_sec": 1.0,
    "retry_max_delay_sec": 30.0,
    "circuit_failure_threshold": 5,
    "circuit_recovery_timeout_sec": 60.0,
    "circuit_half_open_successes": 2,
    "health_check_timeout_sec": 10.0,
}

# 途牛 MCP CLI 配置（TUNIU_API_KEY 走 .env 注入，不在此配置）
TUNIU_MCP_CONFIG = {
    "command": "tuniu",
    "timeout": 30,
    "rpm": 5,
    "rpd": 50,
    "cache_ttl": {
        "hotel:tuniu_hotel_search": 600,
        "hotel:tuniu_hotel_detail": 300,
        "flight:searchLowestPriceFlight": 180,
    },
}

# 高德地图 MCP Server 配置（在此填入你申请的高德 Web 服务 API Key）
AMAP_MCP_CONFIG = {
    "AMAP_KEY": "your_amap_api_key_here",
    "sse_endpoint": "https://mcp.amap.com/sse",
    "timeout": 30,
}
