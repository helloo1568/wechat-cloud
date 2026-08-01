# -*- coding: utf-8 -*-
"""公众号草稿推送客户端（本机运行，零第三方依赖）

用法：
    python push_wechat_draft.py <文章HTML路径> [云托管公网域名]

示例：
    python push_wechat_draft.py "D:/a project/自媒体/公众号/github热榜日报/output/2026-08-01/article_2026-08-01_embed.html" https://xxx.service.tcloudbase.com

功能：解析文章 HTML（标题 + 正文 + 本地图片）→ 组装 multipart →
      POST 到云托管的 /push 接口 → 存公众号草稿箱。
"""
import io
import os
import re
import sys
import uuid
import base64
import mimetypes
import urllib.request


def parse_html(path):
    with open(path, encoding="utf-8") as f:
        html = f.read()
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S)
    title = m.group(1).strip() if m else ""
    m = re.search(r"<body[^>]*>(.*)</body>", html, re.S)
    body = m.group(1) if m else html
    img_srcs = re.findall(r'<img[^>]+src="([^"]+)"', body)
    return title, body, img_srcs


def build_multipart(fields, files):
    boundary = uuid.uuid4().hex
    buf = io.BytesIO()
    for k, v in fields.items():
        buf.write(
            ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
             % (boundary, k, v)).encode("utf-8")
        )
    for i, (field, fpath, fname) in enumerate(files, 1):
        with open(fpath, "rb") as f:
            data = f.read()
        ctype = mimetypes.guess_type(fname)[0] or "application/octet-stream"
        header = ('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\n'
                  'Content-Type: %s\r\n\r\n' % (boundary, field, fname, ctype))
        buf.write(header.encode("utf-8"))
        buf.write(data)
        buf.write(b"\r\n")
    buf.write(("--%s--\r\n" % boundary).encode("utf-8"))
    return buf.getvalue(), boundary


def main():
    if len(sys.argv) < 3:
        print("用法: python push_wechat_draft.py <文章HTML> <云托管公网域名>")
        sys.exit(1)
    html_path = os.path.abspath(sys.argv[1])
    endpoint = sys.argv[2].rstrip("/")
    if not os.path.exists(html_path):
        print("文件不存在:", html_path)
        sys.exit(1)

    title, body, img_srcs = parse_html(html_path)
    if not title:
        print("未解析到标题")
        sys.exit(1)

    base_dir = os.path.dirname(html_path)
    files = []
    tmp_files = []
    for i, src in enumerate(img_srcs, 1):
        if src.startswith("data:"):
            # data:image/png;base64,XXXX  -> 解码为临时文件参与上传
            m = re.match(r"data:image/([a-z0-9.+-]+);base64,(.+)", src, re.S)
            if not m:
                continue
            mime = m.group(1).lower()
            ext = "png" if "png" in mime else ("gif" if "gif" in mime else "jpg")
            try:
                raw = base64.b64decode(m.group(2))
            except Exception:
                print("跳过无法解码的内嵌图:", src[:40])
                continue
            fpath = os.path.join(base_dir, ".wx_tmp_%d.%s" % (i, ext))
            with open(fpath, "wb") as f:
                f.write(raw)
            tmp_files.append(fpath)
            body = body.replace('src="%s"' % src, 'src="{{img%d}}"' % i, 1)
            files.append(("images", fpath, "img%d.%s" % (i, ext)))
            continue
        if src.startswith(("http://", "https://")):
            continue
        fpath = src if os.path.isabs(src) else os.path.join(base_dir, src)
        if not os.path.exists(fpath):
            print("跳过缺失图片:", src)
            continue
        body = body.replace('src="%s"' % src, 'src="{{img%d}}"' % i, 1)
        files.append(("images", fpath, os.path.basename(fpath)))

    # 封面：第一张存在的本地图同时作为 cover 上传（公众号草稿必须有封面 thumb_media_id）
    if files:
        cover = files[0][1]
        files.insert(0, ("cover", cover, os.path.basename(cover)))
        print("封面:", os.path.basename(cover))

    fields = {"title": title, "content": body}
    data, boundary = build_multipart(fields, files)
    print("标题:", title)
    print("正文图:", len(files) - 1, "张（含封面 1 张）")

    req = urllib.request.Request(
        endpoint + "/push",
        data=data,
        method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            print(resp.read().decode("utf-8"))
    finally:
        # 清理 base64 解码的临时图片
        for t in tmp_files:
            try:
                os.remove(t)
            except OSError:
                pass


if __name__ == "__main__":
    main()
