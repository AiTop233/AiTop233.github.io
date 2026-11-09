#!/usr/bin/env python3
"""
下载文件夹归档整理脚本
用法：
  python organize_downloads.py --dry-run   预览模式
  python organize_downloads.py --run       正式执行
"""

import os
import sys
import shutil
import re
from collections import defaultdict

DOWNLOADS = os.path.expanduser("~/Downloads")

# ============================================================
# 文件夹定义
# ============================================================
FOLDERS = [
    "02-金融三剑客",
    "03-生财有术精华",
    "04-副业SC精华",
    "05-费曼茶馆",
    "06-体制主任",
    "07-鉴茶财富",
    "08-新闻实验室",
    "09-U君笔记",
    "10-砖瓦厂",
    "11-群分享",
    "12-记忆承载",
    "13-毛选",
    "14-专属群",
    "15-赢在8小时之外",
    "16-屠龙手段",
    "17-丁辰灵",
    "18-先觉者",
    "19-圆方",
    "20-灰玻璃",
    "21-野心范",
    "22-九边",
    "23-其他作者合集",
    "24-单篇文章",
    "25-书籍与学术",
    "26-电子书EPUB",
    "27-数据表格Excel",
    "28-图片",
    "29-压缩包",
    "30-文档DocxTxt",
    "31-知乎文章MD",
    "32-音频课程",
    "33-视频",
    "34-数据备份JSON",
    "35-书签HTML",
    "36-软件安装包",
]

# PDF 关键词规则（按优先级排列）
PDF_RULES = [
    # (关键词, 目标文件夹) — 不区分大小写
    ("金融三剑客", "02-金融三剑客"),
    ("副业SC精华", "04-副业SC精华"),
    ("生财", "03-生财有术精华"),
    ("费曼", "05-费曼茶馆"),
    ("体制主任", "06-体制主任"),
    ("鉴茶", "07-鉴茶财富"),
    ("新闻实验室", "08-新闻实验室"),
    ("U君", "09-U君笔记"),
    ("砖瓦厂", "10-砖瓦厂"),
    ("群分享", "11-群分享"),
    ("记忆承载", "12-记忆承载"),
    ("毛选", "13-毛选"),
    ("专属群", "14-专属群"),
    ("赢在8小时之外", "15-赢在8小时之外"),
    ("8.13付费文", "15-赢在8小时之外"),
    ("屠龙", "16-屠龙手段"),
    ("丁辰灵", "17-丁辰灵"),
    ("先觉者", "18-先觉者"),
    ("圆方", "19-圆方"),
    ("灰玻璃", "20-灰玻璃"),
    ("野心范", "21-野心范"),
    ("九边", "22-九边"),
    # 其他作者合集
    ("猫哥", "23-其他作者合集"),
    ("达叔", "23-其他作者合集"),
    ("守夜人总司令", "23-其他作者合集"),
    ("大树乡", "23-其他作者合集"),
    ("幻幻话你知", "23-其他作者合集"),
    ("雪球花甲老头", "23-其他作者合集"),
    ("万叔", "23-其他作者合集"),
    ("参考周刊", "23-其他作者合集"),
    ("参考答案", "23-其他作者合集"),
    ("第三只眼观", "23-其他作者合集"),
    ("大英良心汉弗莱", "23-其他作者合集"),
    ("六爷阿旦", "23-其他作者合集"),
    ("剑客说", "23-其他作者合集"),
    ("显明易说", "23-其他作者合集"),
    ("五千叔", "23-其他作者合集"),
    ("产品沉思录", "23-其他作者合集"),
    ("段永平", "23-其他作者合集"),
    ("子明私享汇", "23-其他作者合集"),
    ("老端", "23-其他作者合集"),
    ("熊道笔记", "23-其他作者合集"),
    ("创始人笔记", "23-其他作者合集"),
    ("挨踢牛魔王", "23-其他作者合集"),
    ("卢克文", "23-其他作者合集"),
    ("修德坊", "23-其他作者合集"),
    ("张津铭", "23-其他作者合集"),
    ("诚长的笔杆子", "23-其他作者合集"),
    ("情感六处", "23-其他作者合集"),
    ("珍大户", "23-其他作者合集"),
    ("盛京剑客", "23-其他作者合集"),
    ("老马的笔记", "23-其他作者合集"),
    ("北辰青年", "23-其他作者合集"),
    ("放学以后", "23-其他作者合集"),
    ("互联网精华", "23-其他作者合集"),
    ("顶级社群精华", "23-其他作者合集"),
    ("SC精华", "23-其他作者合集"),
    ("caoz", "23-其他作者合集"),
    ("A视野", "23-其他作者合集"),
    ("司马林", "23-其他作者合集"),
    ("猫笔刀", "23-其他作者合集"),
    ("王铁匠", "23-其他作者合集"),
    ("徐戈", "23-其他作者合集"),
    ("顾小北", "23-其他作者合集"),
    ("冯唐", "23-其他作者合集"),
    ("甄琦学长", "23-其他作者合集"),
    ("老A知识星球", "23-其他作者合集"),
    ("公周", "23-其他作者合集"),
    ("晓书童", "23-其他作者合集"),
    # 书籍与学术
    ("z-library", "25-书籍与学术"),
    ("z-lib", "25-书籍与学术"),
    ("anna's archive", "25-书籍与学术"),
    ("normalpdf", "25-书籍与学术"),
    ("preprint", "25-书籍与学术"),
    ("诠释学", "25-书籍与学术"),
    ("文心雕龙", "25-书籍与学术"),
    ("词彩", "25-书籍与学术"),
    ("杨明照", "25-书籍与学术"),
    ("叔本华", "25-书籍与学术"),
    ("作为意欲", "25-书籍与学术"),
    ("附录和补遗", "25-书籍与学术"),
    ("支配社会学", "25-书籍与学术"),
    ("民法解释学", "25-书籍与学术"),
    ("社会研究方法", "25-书籍与学术"),
    ("个人形成论", "25-书籍与学术"),
    ("情绪词典", "25-书籍与学术"),
    ("中国史学发微", "25-书籍与学术"),
    ("哲学与人生", "25-书籍与学术"),
    ("哲学意义上的需求论", "25-书籍与学术"),
    ("新媒体的逻辑", "25-书籍与学术"),
    ("语言的第七功能", "25-书籍与学术"),
    ("鸣沙书系", "25-书籍与学术"),
    ("风格感觉", "25-书籍与学术"),
    ("素书", "25-书籍与学术"),
    ("人工智能", "25-书籍与学术"),
    ("neo4j", "25-书籍与学术"),
    ("react全栈", "25-书籍与学术"),
    ("编译原理", "25-书籍与学术"),
    ("编译器设计", "25-书籍与学术"),
    ("程序员的线性代数", "25-书籍与学术"),
    ("推荐系统实践", "25-书籍与学术"),
    ("网络基本功", "25-书籍与学术"),
    ("sem一家之言", "25-书籍与学术"),
    ("ladr4echinese", "25-书籍与学术"),
    ("编程和编码", "25-书籍与学术"),
    ("graph data science", "25-书籍与学术"),
    ("the mom test", "25-书籍与学术"),
    ("the philosophy of exemplarity", "25-书籍与学术"),
    ("beyond pleasure", "25-书籍与学术"),
    ("instant enlightenment", "25-书籍与学术"),
    ("startupgenome", "25-书籍与学术"),
    ("kuhletal2020", "25-书籍与学术"),
    ("写作教学应重视概念的澄清", "25-书籍与学术"),
    ("大概念的误解", "25-书籍与学术"),
    ("课程改革历史研究", "25-书籍与学术"),
    ("聪明人更愿意创业吗", "25-书籍与学术"),
    ("本体论承诺", "25-书籍与学术"),
    ("公信力和政治问责", "25-书籍与学术"),
    ("产业与文明", "25-书籍与学术"),
]

# 扩展名分类规则
EXT_RULES = {
    "26-电子书EPUB": [".epub", ".mobi"],
    "27-数据表格Excel": [".xlsx"],
    "28-图片": [".png", ".jpg", ".jpeg", ".avif", ".webp"],
    "29-压缩包": [".zip", ".7z", ".rar"],
    "30-文档DocxTxt": [".docx", ".doc", ".txt"],
    "31-知乎文章MD": [".md"],
    "32-音频课程": [".mp3", ".m4a", ".wav", ".flac"],
    "33-视频": [".mp4", ".mov", ".avi", ".mkv"],
    "34-数据备份JSON": [".json"],
    "35-书签HTML": [".html", ".htm"],
    "36-软件安装包": [".exe", ".msi", ".dmg", ".apk", ".msix"],
}

# 特殊扩展名映射
SPECIAL_EXT = {
    ".ttc": "36-软件安装包",
    ".traineddata": "36-软件安装包",
    ".opml": "34-数据备份JSON",
    ".js": "36-软件安装包",
    ".ini": "30-文档DocxTxt",
    ".mhtml": "30-文档DocxTxt",
    ".excalidraw": "30-文档DocxTxt",
    ".p": "25-书籍与学术",
}


def match_pdf(filename: str) -> str | None:
    """匹配 PDF 文件名到目标文件夹"""
    lower = filename.lower()
    for keyword, target in PDF_RULES:
        if keyword.lower() in lower:
            return target
    return None


def classify_by_ext(filename: str) -> str | None:
    """按扩展名分类非 PDF 文件"""
    _, ext = os.path.splitext(filename)
    ext = ext.lower()

    # 先检查特殊映射
    if ext in SPECIAL_EXT:
        return SPECIAL_EXT[ext]

    # 再检查通用规则
    for target, exts in EXT_RULES.items():
        if ext in exts:
            return target

    return None


def main():
    dry_run = "--run" not in sys.argv

    if dry_run:
        print("\033[33m====== 预览模式 (Dry Run) — 仅统计，不移动文件 ======\033[0m\n")
    else:
        print("\033[32m====== 正式执行 — 将移动文件 ======\033[0m\n")

    os.chdir(DOWNLOADS)
    stats = defaultdict(int)
    total = 0
    errors = []

    # 预先创建文件夹
    if not dry_run:
        for folder in FOLDERS:
            os.makedirs(folder, exist_ok=True)
        print("\033[34m[INFO]\033[0m 文件夹已就绪\n")

    # Step 1: 分类 PDF
    print("\033[34m[INFO]\033[0m Step 1: 分类 PDF 文件...")
    pdf_files = [f for f in os.listdir(".") if os.path.isfile(f) and f.lower().endswith(".pdf")]
    pdf_matched = 0
    pdf_unmatched = 0

    for pdf in pdf_files:
        target = match_pdf(pdf)
        if target is None:
            target = "24-单篇文章"
            pdf_unmatched += 1
        else:
            pdf_matched += 1

        if not dry_run:
            try:
                dest = os.path.join(target, pdf)
                if os.path.abspath(pdf) != os.path.abspath(dest):
                    shutil.move(pdf, dest)
            except Exception as e:
                errors.append(f"移动失败: {pdf} → {target}: {e}")
        stats[target] += 1
        total += 1

    print(f"  PDF: 共 {len(pdf_files)} 个, 已匹配 {pdf_matched}, 未匹配→单篇文章 {pdf_unmatched}\n")

    # Step 2: 分类非 PDF
    print("\033[34m[INFO]\033[0m Step 2: 分类非 PDF 文件...")
    other_files = [f for f in os.listdir(".") if os.path.isfile(f) and not f.lower().endswith(".pdf")]
    unmatched_other = 0

    for f in other_files:
        target = classify_by_ext(f)
        if target is None:
            # 未知类型 → 单篇文章
            target = "24-单篇文章"
            unmatched_other += 1

        if not dry_run:
            try:
                dest = os.path.join(target, f)
                if os.path.abspath(f) != os.path.abspath(dest):
                    shutil.move(f, dest)
            except Exception as e:
                errors.append(f"移动失败: {f} → {target}: {e}")
        stats[target] += 1
        total += 1

    print(f"  非PDF: 共 {len(other_files)} 个, 未识别 {unmatched_other} 个\n")

    # Step 3: 合并已有文件夹
    print("\033[34m[INFO]\033[0m Step 3: 合并已有文件夹...")

    # 合并费曼茶馆
    feiman_old = "250124费曼茶馆10篇付费文"
    if os.path.isdir(feiman_old):
        for f in os.listdir(feiman_old):
            fp = os.path.join(feiman_old, f)
            if os.path.isfile(fp):
                target = match_pdf(f) or "24-单篇文章"
                if not dry_run:
                    try:
                        shutil.move(fp, os.path.join("05-费曼茶馆", f))
                    except Exception as e:
                        errors.append(f"移动失败: {fp}: {e}")
                stats["05-费曼茶馆"] += 1
                total += 1
        if not dry_run:
            try:
                os.rmdir(feiman_old)
                print(f"  已合并并删除: {feiman_old}/")
            except OSError:
                print(f"  已合并但目录非空: {feiman_old}/")

    # 合并 2024-09等2个文件...
    jth_dir = "2024-09等2个文件-2025.04.03-100050-JTh"
    if os.path.isdir(jth_dir):
        for f in os.listdir(jth_dir):
            fp = os.path.join(jth_dir, f)
            if os.path.isfile(fp):
                target = match_pdf(f) or "24-单篇文章"
                if not dry_run:
                    try:
                        shutil.move(fp, os.path.join(target, f))
                    except Exception as e:
                        errors.append(f"移动失败: {fp}: {e}")
                stats[target] += 1
                total += 1
        if not dry_run:
            try:
                os.rmdir(jth_dir)
                print(f"  已归类并删除: {jth_dir}/")
            except OSError:
                print(f"  已归类但目录非空: {jth_dir}/")

    # Step 4: 清理空目录
    for d in ["abc", "temp"]:
        if os.path.isdir(d) and not os.listdir(d):
            if not dry_run:
                os.rmdir(d)
                print(f"  已删除空目录: {d}/")
            stats["(清理空目录)"] += 1

    print()

    # ============================================================
    # 最终统计
    # ============================================================
    print("=" * 50)
    if dry_run:
        print("\033[33m====== 预览完成 (Dry Run) — 未实际移动文件 ======\033[0m")
    else:
        print("\033[32m====== 整理完成！======\033[0m")

    print(f"\n总文件数: {total}")
    print("\n各文件夹分布:")

    for folder in FOLDERS:
        count = stats.get(folder, 0)
        if count > 0:
            print(f"  {folder:<30} {count:>5} 个")

    clean = stats.get("(清理空目录)", 0)
    if clean > 0:
        print(f"  {'(清理空目录)':<30} {clean:>5} 个")

    # 检查剩余文件
    remaining = len([f for f in os.listdir(".") if os.path.isfile(f)])
    print(f"\n\033[34m[INFO]\033[0m 根目录剩余文件: {remaining} 个（含 desktop.ini 等系统文件）")

    if errors:
        print(f"\n\033[31m[ERR]\033[0m {len(errors)} 个错误:")
        for e in errors[:10]:
            print(f"  - {e}")

    print()
    if dry_run:
        print("确认无误后执行: python ~/ZCodeProject/organize_downloads.py --run")
    print("Done!")


if __name__ == "__main__":
    main()
