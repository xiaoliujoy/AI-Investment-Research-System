# -*- coding: utf-8 -*-
"""推送配置：优先读环境变量，其次读 backend/.env（KEY=VALUE，勿提交真实密钥）。

渠道状态（2026-07-17 起）：
  ── 已取消：企微(wecom) / 飞书(feishu) / Server酱(serverchan) —— 推送效果差，停用。
  ── 仅保留：微信公众号(mp) —— 作为唯一对外发布渠道。

保留的配置项（仅 mp 生效）：
  MP_APPID             微信公众号 appid
  MP_APPSECRET         微信公众号 appsecret
  MP_AUTHOR_NAME       公众号文章作者（可选）

（WECHAT_WEBHOOK_URL / FEISHU_WEBHOOK_URL / FEISHU_SECRET / SERVERCHAN_SENDKEY
 仍可被 .env 读取，但 channel_enabled() 不再启用这三个渠道。）
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_env_file():
    p = os.path.join(ROOT, ".env")
    env = {}
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                if v:
                    env[k.strip()] = v
    return env


_ENV = _load_env_file()


def get(name, default=None):
    v = os.environ.get(name)
    if v:
        return v
    return _ENV.get(name, default)


def channel_enabled():
    """返回当前已启用（可推送）的渠道列表。

    2026-07-17 起仅保留微信公众号（mp）；企微 / 飞书 / Server酱 已取消。
    即使 .env 中仍配置了对应密钥，也不再启用这三个渠道。
    """
    out = []
    if get("MP_APPID") and get("MP_APPSECRET"):
        out.append("mp")
    return out
