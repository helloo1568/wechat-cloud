# -*- coding: utf-8 -*-
"""微信云托管 - 公众号文章推送服务

功能：接收本机客户端推送的图文，自动完成「封面/正文图上传 + 新建草稿」，
把文章存进公众号草稿箱（不自动发布）。

两种运行模式：
  1. 云调用模式（默认，部署到微信云托管后使用）：
     开启「开放接口服务」后，容器内直接 HTTP 调 http://api.weixin.qq.com/cgi-bin/*
     （不带 access_token），由云托管自动鉴权，免 IP 白名单。
  2. 普通模式（本机调试/传统部署）：
     设 USE_CLOUD_CALL=0 并配置 WX_APPID / WX_APPSECRET，用 appid+secret 换 token 再调
     （此模式需要把出口 IP 加入公众号白名单）。
"""
import os
import json
import time
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

USE_CLOUD_CALL = os.environ.get("USE_CLOUD_CALL", "1") == "1"
API_BASE = os.environ.get("WX_API_BASE", "http://api.weixin.qq.com")  # 云调用走 http
APPID = os.environ.get("WX_APPID", "")
SECRET = os.environ.get("WX_APPSECRET", "")

_token = {"token": None, "expires": 0}


def get_token():
    """普通模式：appid/secret 换 access_token（带 2 小时缓存）"""
    now = time.time()
    if _token["token"] and _token["expires"] > now + 60:
        return _token["token"]
    r = requests.get(
        "https://api.weixin.qq.com/cgi-bin/token",
        params={"grant_type": "client_credential", "appid": APPID, "secret": SECRET},
        timeout=15,
    )
    d = r.json()
    if "access_token" not in d:
        raise RuntimeError("token failed: %s" % d)
    _token["token"] = d["access_token"]
    _token["expires"] = now + d.get("expires_in", 7200)
    return _token["token"]


def wx_post(path, params=None, **kw):
    """调微信接口：云调用模式不带 access_token，普通模式自动带"""
    if USE_CLOUD_CALL:
        return requests.post(API_BASE + path, timeout=90, **kw)
    token = get_token()
    return requests.post(API_BASE + path, params={**(params or {}), "access_token": token}, timeout=90, **kw)


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True, "mode": "cloud_call" if USE_CLOUD_CALL else "normal"})


@app.route("/push", methods=["POST"])
def push():
    """multipart/form-data:
        title     必填，文章标题
        author    可选
        digest    可选，摘要（留空则微信自动抓取正文前 54 字）
        content   必填，正文 HTML；正文图用 {{img1}}..{{imgN}} 占位符
        images[]  正文图文件（可选，按顺序对应占位符）
        cover     封面图文件（可选，没有则微信用首图兜底）
    """
    title = (request.form.get("title") or "").strip()
    if not title:
        return jsonify({"ok": False, "error": "title required"}), 400
    author = (request.form.get("author") or "").strip()
    digest = (request.form.get("digest") or "").strip()
    content = request.form.get("content") or ""
    images = request.files.getlist("images")
    cover = request.files.get("cover")

    # 1) 封面 -> 永久素材 thumb_media_id（可选）
    thumb_media_id = None
    if cover:
        r = wx_post(
            "/cgi-bin/material/add_material",
            params={"type": "image"},
            files={"media": (cover.filename or "cover.jpg", cover.stream, cover.mimetype or "image/jpeg")},
        )
        d = r.json()
        if "media_id" not in d:
            return jsonify({"ok": False, "error": "cover upload failed", "detail": d}), 502
        thumb_media_id = d["media_id"]

    # 2) 正文图 -> 微信图床 URL，替换占位符
    for i, img in enumerate(images, 1):
        r = wx_post(
            "/cgi-bin/media/uploadimg",
            files={"media": (img.filename or "img%d.jpg" % i, img.stream, img.mimetype or "image/jpeg")},
        )
        d = r.json()
        if "url" not in d:
            return jsonify({"ok": False, "error": "img%d upload failed" % i, "detail": d}), 502
        content = content.replace("{{img%d}}" % i, d["url"])

    # 3) 新建草稿
    article = {
        "title": title,
        "author": author,
        "digest": digest,
        "content": content,
        "need_open_comment": 1,
        "only_fans_can_comment": 0,
    }
    if thumb_media_id:
        article["thumb_media_id"] = thumb_media_id
    # 关键：requests 的 json= 默认 ensure_ascii=True 会把中文转成 \uXXXX，
    # 微信端会按字面显示乱码（如 \u8fd8）。必须手动 ensure_ascii=False。
    payload = json.dumps({"articles": [article]}, ensure_ascii=False).encode("utf-8")
    r = wx_post(
        "/cgi-bin/draft/add",
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    d = r.json()
    if d.get("media_id"):
        return jsonify({"ok": True, "media_id": d["media_id"]})
    return jsonify({"ok": False, "error": "draft add failed", "detail": d}), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 80)))
