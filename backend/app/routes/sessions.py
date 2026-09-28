"""会话读取接口。

GET /sessions        —— 列表（id / title / updated_at），供前端侧栏渲染
GET /sessions/{id}   —— 完整消息，供刷新页面后恢复，包含工具调用记录与地图打点
"""
from fastapi import APIRouter

router = APIRouter()


# TODO(Day 3): 两个 GET 端点
