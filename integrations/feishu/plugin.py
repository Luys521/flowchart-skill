# -*- coding: utf-8 -*-
"""plugin.py — 飞书插件入口（register）。

由核心 scripts/plugin.py 的 discover() 在插件启用后动态加载；本文件把飞书各连接器
注册到通用扩展点。核心不 import 本文件，关闭插件时这些扩展一个都不存在。
"""


def register(registry, config, ctx):
    """注册飞书的 sources / publishers / commands 扩展。"""
    from sources import approval, doc_export
    from publishers import feishu_push, feishu_doc
    from feishu_client import build_client

    # 材料来源
    registry.register('sources', 'feishu_doc_export', doc_export.fetch,
                      desc='飞书云文档导出（用户身份）', identity='user')
    registry.register('sources', 'feishu_approval', approval.fetch,
                      desc='飞书审批实例拉取（应用身份）', identity='tenant')

    # 产物发布
    registry.register('publishers', 'feishu', feishu_push.publish,
                      desc='飞书云盘 + IM 消息发布（应用身份）', identity='tenant')
    registry.register('publishers', 'feishu_doc', feishu_doc.publish_doc,
                      desc='飞书云文档 + 可编辑画板发布（应用身份）', identity='tenant')

    # 附加命令：用户授权登录（OAuth）
    def login(open_browser=True, **kwargs):
        return build_client(config).login(open_browser=open_browser)

    registry.register('commands', 'feishu_login', login,
                      desc='飞书用户授权登录（导出权限，一次性）')

    return registry
