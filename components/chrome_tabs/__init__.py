import os
import streamlit.components.v1 as components

_component_path = os.path.dirname(os.path.abspath(__file__))
_chrome_tabbar = components.declare_component("chrome_tabbar", path=_component_path)

def render_chrome_tabs(tabs, active_id, archived_count, key="chrome_tabs_widget"):
    """
    像素级复刻 Chrome 原生标签栏组件：
    - tabs: [{'id': ..., 'title': ..., 'icon': ..., 'is_starred': bool}, ...]
    - active_id: 当前激活的会话 ID
    - archived_count: 归档数量
    返回值:
    - {'action': 'select_tab'|'close_tab'|'toggle_star'|'add_tab'|'open_history', 'payload': ...}
    """
    return _chrome_tabbar(
        tabs=tabs,
        active_id=active_id,
        archived_count=archived_count,
        key=key,
        default=None
    )
