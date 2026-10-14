"""pytest 全局配置：在任何测试模块 import 之前执行。

.env 里配了真实的 Langfuse key。测试（尤其是会走 lifespan 的 API 测试）不应该往线上项目
写数据，所以这里用空的环境变量覆盖掉——pydantic-settings 里环境变量优先级高于 .env。
"""
import os

os.environ["LANGFUSE_PUBLIC_KEY"] = ""
os.environ["LANGFUSE_SECRET_KEY"] = ""
