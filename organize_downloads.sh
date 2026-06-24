#!/bin/bash
#
# 下载文件夹归档整理脚本
# 用法：
#   ./organize_downloads.sh --dry-run   预览模式（只统计不执行）
#   ./organize_downloads.sh --run       正式执行
#

set -euo pipefail

DOWNLOADS="$HOME/Downloads"

# ============================================================
# 颜色输出
# ============================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }

# ============================================================
# 参数解析
# ============================================================
DRY_RUN=true
if [[ "${1:-}" == "--run" ]]; then
    DRY_RUN=false
elif [[ "${1:-}" == "--dry-run" ]] || [[ -z "${1:-}" ]]; then
    DRY_RUN=true
else
    echo "用法: $0 [--dry-run|--run]"
    exit 1
fi

if $DRY_RUN; then
    warn "====== 预览模式 (Dry Run) — 仅统计，不移动文件 ======"
    echo ""
fi

cd "$DOWNLOADS"

# ============================================================
# 统计变量
# ============================================================
declare -A STATS
TOTAL_MOVED=0

move_file() {
    local file="$1"
    local target_dir="$2"
    
    # 避免移动自身
    if [[ "$(dirname "$file")" == "$target_dir" ]]; then
        return 0
    fi
    
    STATS["$target_dir"]=$(( ${STATS["$target_dir"]:-0} + 1 ))
    TOTAL_MOVED=$((TOTAL_MOVED + 1))
    
    if ! $DRY_RUN; then
        mkdir -p "$target_dir" 2>/dev/null
        mv "$file" "$target_dir/" 2>/dev/null || warn "无法移动: $file"
    fi
}

# ============================================================
# Step 0: 创建目标文件夹
# ============================================================
info "Step 0: 创建分类文件夹..."
FOLDERS=(
    "02-金融三剑客"
    "03-生财有术精华"
    "04-副业SC精华"
    "05-费曼茶馆"
    "06-体制主任"
    "07-鉴茶财富"
    "08-新闻实验室"
    "09-U君笔记"
    "10-砖瓦厂"
    "11-群分享"
    "12-记忆承载"
    "13-毛选"
    "14-专属群"
    "15-赢在8小时之外"
    "16-屠龙手段"
    "17-丁辰灵"
    "18-先觉者"
    "19-圆方"
    "20-灰玻璃"
    "21-野心范"
    "22-九边"
    "23-其他作者合集"
    "24-单篇文章"
    "25-书籍与学术"
    "26-电子书EPUB"
    "27-数据表格Excel"
    "28-图片"
    "29-压缩包"
    "30-文档DocxTxt"
    "31-知乎文章MD"
    "32-音频课程"
    "33-视频"
    "34-数据备份JSON"
    "35-书签HTML"
    "36-软件安装包"
)

if ! $DRY_RUN; then
    for folder in "${FOLDERS[@]}"; do
        mkdir -p "$folder" 2>/dev/null
    done
    ok "文件夹已就绪"
fi
echo ""

# ============================================================
# 定义 PDF 匹配规则
# ============================================================
PDF_RULES=(
    "金融三剑客|02-金融三剑客"
    "副业SC精华|04-副业SC精华"
    "生财|03-生财有术精华"
    "费曼|05-费曼茶馆"
    "体制主任|06-体制主任"
    "鉴茶|07-鉴茶财富"
    "新闻实验室|08-新闻实验室"
    "U君|09-U君笔记"
    "砖瓦厂|10-砖瓦厂"
    "群分享|11-群分享"
    "记忆承载|12-记忆承载"
    "毛选|13-毛选"
    "专属群|14-专属群"
    "赢在8小时之外|15-赢在8小时之外"
    "8.13付费文|15-赢在8小时之外"
    "屠龙|16-屠龙手段"
    "丁辰灵|17-丁辰灵"
    "先觉者|18-先觉者"
    "圆方|19-圆方"
    "灰玻璃|20-灰玻璃"
    "野心范|21-野心范"
    "九边|22-九边"
    "猫哥|23-其他作者合集"
    "达叔|23-其他作者合集"
    "守夜人总司令|23-其他作者合集"
    "大树乡|23-其他作者合集"
    "幻幻话你知|23-其他作者合集"
    "雪球花甲老头|23-其他作者合集"
    "万叔|23-其他作者合集"
    "参考周刊|23-其他作者合集"
    "参考答案|23-其他作者合集"
    "第三只眼观|23-其他作者合集"
    "大英良心汉弗莱|23-其他作者合集"
    "六爷阿旦|23-其他作者合集"
    "剑客说|23-其他作者合集"
    "显明易说|23-其他作者合集"
    "五千叔|23-其他作者合集"
    "产品沉思录|23-其他作者合集"
    "段永平|23-其他作者合集"
    "子明私享汇|23-其他作者合集"
    "老端|23-其他作者合集"
    "熊道笔记|23-其他作者合集"
    "创始人笔记|23-其他作者合集"
    "挨踢牛魔王|23-其他作者合集"
    "卢克文|23-其他作者合集"
    "修德坊|23-其他作者合集"
    "张津铭|23-其他作者合集"
    "诚长的笔杆子|23-其他作者合集"
    "情感六处|23-其他作者合集"
    "珍大户|23-其他作者合集"
    "盛京剑客|23-其他作者合集"
    "老马的笔记|23-其他作者合集"
    "北辰青年|23-其他作者合集"
    "放学以后|23-其他作者合集"
    "互联网精华|23-其他作者合集"
    "顶级社群精华|23-其他作者合集"
    "SC精华|23-其他作者合集"
    "caoz|23-其他作者合集"
    "A视野|23-其他作者合集"
    "司马林|23-其他作者合集"
    "猫笔刀|23-其他作者合集"
    "王铁匠|23-其他作者合集"
    "徐戈|23-其他作者合集"
    "顾小北|23-其他作者合集"
    "冯唐|23-其他作者合集"
    "甄琦学长|23-其他作者合集"
    "老A知识星球|23-其他作者合集"
    "公周|23-其他作者合集"
    "晓书童|23-其他作者合集"
    "Z-Library|25-书籍与学术"
    "z-library|25-书籍与学术"
    "Z-Lib|25-书籍与学术"
    "z-lib|25-书籍与学术"
    "Anna's Archive|25-书籍与学术"
    "NormalPdf|25-书籍与学术"
    "Preprint|25-书籍与学术"
    "诠释学|25-书籍与学术"
    "文心雕龙|25-书籍与学术"
    "词彩|25-书籍与学术"
    "杨明照|25-书籍与学术"
    "叔本华|25-书籍与学术"
    "作为意欲|25-书籍与学术"
    "附录和补遗|25-书籍与学术"
    "支配社会学|25-书籍与学术"
    "民法解释学|25-书籍与学术"
    "社会研究方法|25-书籍与学术"
    "个人形成论|25-书籍与学术"
    "情绪词典|25-书籍与学术"
    "中国史学发微|25-书籍与学术"
    "哲学与人生|25-书籍与学术"
    "哲学意义上的需求论|25-书籍与学术"
    "新媒体的逻辑|25-书籍与学术"
    "语言的第七功能|25-书籍与学术"
    "鸣沙书系|25-书籍与学术"
    "风格感觉|25-书籍与学术"
    "素书|25-书籍与学术"
    "人工智能|25-书籍与学术"
    "Neo4j|25-书籍与学术"
    "React全栈|25-书籍与学术"
    "编译原理|25-书籍与学术"
    "编译器设计|25-书籍与学术"
    "程序员的线性代数|25-书籍与学术"
    "推荐系统实践|25-书籍与学术"
    "网络基本功|25-书籍与学术"
    "SEM一家之言|25-书籍与学术"
    "LADR4eChinese|25-书籍与学术"
    "编程和编码|25-书籍与学术"
    "Graph Data Science|25-书籍与学术"
    "The Mom Test|25-书籍与学术"
    "The Philosophy of Exemplarity|25-书籍与学术"
    "Beyond Pleasure|25-书籍与学术"
    "Instant Enlightenment|25-书籍与学术"
    "StartupGenome|25-书籍与学术"
    "Kuhletal2020|25-书籍与学术"
    "写作教学应重视概念的澄清|25-书籍与学术"
    "大概念的误解|25-书籍与学术"
    "课程改革历史研究|25-书籍与学术"
    "聪明人更愿意创业吗|25-书籍与学术"
    "本体论承诺|25-书籍与学术"
    "公信力和政治问责|25-书籍与学术"
    "产业与文明|25-书籍与学术"
)

# ============================================================
# Step 1: 分类 PDF
# ============================================================
info "Step 1: 扫描并分类 PDF 文件..."
PDF_COUNT=0; PDF_MATCHED=0; PDF_UNMATCHED=0

for pdf in *.pdf; do
    [[ -f "$pdf" ]] || continue
    PDF_COUNT=$((PDF_COUNT + 1))
    
    matched=false
    for rule in "${PDF_RULES[@]}"; do
        keyword="${rule%%|*}"
        target="${rule##*|}"
        if echo "$pdf" | grep -qi "$keyword"; then
            move_file "$pdf" "$target"
            matched=true
            PDF_MATCHED=$((PDF_MATCHED + 1))
            break
        fi
    done
    
    if ! $matched; then
        move_file "$pdf" "24-单篇文章"
        PDF_UNMATCHED=$((PDF_UNMATCHED + 1))
    fi
done

info "PDF: 共 $PDF_COUNT 个, 已匹配 $PDF_MATCHED, 未匹配→单篇文章 $PDF_UNMATCHED"
echo ""

# ============================================================
# Step 2: 分类非 PDF
# ============================================================
info "Step 2: 分类非 PDF 文件..."

# EPUB + MOBI
for f in *.epub *.mobi; do
    [[ -f "$f" ]] || continue
    move_file "$f" "26-电子书EPUB"
done

# XLSX
for f in *.xlsx; do
    [[ -f "$f" ]] || continue
    move_file "$f" "27-数据表格Excel"
done

# 图片
for ext in png jpg jpeg avif; do
    for f in *."$ext"; do
        [[ -f "$f" ]] || continue
        move_file "$f" "28-图片"
    done
done

# 压缩包
for ext in zip 7z rar; do
    for f in *."$ext"; do
        [[ -f "$f" ]] || continue
        move_file "$f" "29-压缩包"
    done
done

# 文档
for ext in docx doc txt; do
    for f in *."$ext"; do
        [[ -f "$f" ]] || continue
        move_file "$f" "30-文档DocxTxt"
    done
done

# Markdown
for f in *.md; do
    [[ -f "$f" ]] || continue
    move_file "$f" "31-知乎文章MD"
done

# 音频
for ext in mp3 m4a; do
    for f in *."$ext"; do
        [[ -f "$f" ]] || continue
        move_file "$f" "32-音频课程"
    done
done

# 视频
for f in *.mp4; do
    [[ -f "$f" ]] || continue
    move_file "$f" "33-视频"
done

# JSON
for f in *.json; do
    [[ -f "$f" ]] || continue
    move_file "$f" "34-数据备份JSON"
done

# HTML
for f in *.html; do
    [[ -f "$f" ]] || continue
    move_file "$f" "35-书签HTML"
done

# 安装包
for ext in exe msi dmg apk msix; do
    for f in *."$ext"; do
        [[ -f "$f" ]] || continue
        move_file "$f" "36-软件安装包"
    done
done

# 其他
for f in *.ttc *.traineddata *.opml *.js *.ini *.mhtml *.excalidraw *.p; do
    [[ -f "$f" ]] || continue
    case "$f" in
        *.traineddata|*.ttc) move_file "$f" "36-软件安装包" ;;
        *.opml)              move_file "$f" "34-数据备份JSON" ;;
        *.js)                move_file "$f" "36-软件安装包" ;;
        *.ini)               move_file "$f" "30-文档DocxTxt" ;;
        *.mhtml)             move_file "$f" "30-文档DocxTxt" ;;
        *.excalidraw)        move_file "$f" "30-文档DocxTxt" ;;
        *.p)                 move_file "$f" "25-书籍与学术" ;;
        *)                   move_file "$f" "24-单篇文章" ;;
    esac
done

echo ""

# ============================================================
# Step 3: 合并已有文件夹
# ============================================================
info "Step 3: 合并已有文件夹..."

# 费曼茶馆
if [[ -d "250124费曼茶馆10篇付费文" ]]; then
    for f in "250124费曼茶馆10篇付费文"/*; do
        [[ -f "$f" ]] || continue
        move_file "$f" "05-费曼茶馆"
    done
    if ! $DRY_RUN; then
        rmdir "250124费曼茶馆10篇付费文" 2>/dev/null || true
    fi
fi

# 2024-09等2个文件...
JTH_DIR="2024-09等2个文件-2025.04.03-100050-JTh"
if [[ -d "$JTH_DIR" ]]; then
    for f in "$JTH_DIR"/*; do
        [[ -f "$f" ]] || continue
        matched=false
        for rule in "${PDF_RULES[@]}"; do
            keyword="${rule%%|*}"
            target="${rule##*|}"
            if echo "$(basename "$f")" | grep -qi "$keyword"; then
                move_file "$f" "$target"
                matched=true
                break
            fi
        done
        if ! $matched; then
            move_file "$f" "24-单篇文章"
        fi
    done
    if ! $DRY_RUN; then
        rmdir "$JTH_DIR" 2>/dev/null || true
    fi
fi

# 清理空目录
for d in abc temp; do
    if [[ -d "$d" ]] && [[ -z "$(ls -A "$d" 2>/dev/null)" ]]; then
        if ! $DRY_RUN; then
            rmdir "$d" 2>/dev/null && ok "已删除空目录: $d/"
        else
            STATS["(清理空目录)"]=$(( ${STATS["(清理空目录)"]:-0} + 1 ))
        fi
    fi
done

echo ""

# ============================================================
# 最终统计
# ============================================================
echo "========================================"
if $DRY_RUN; then
    warn "====== 预览完成 (Dry Run) — 未实际移动文件 ======"
else
    ok "====== 整理完成！======"
fi

echo "总文件数: $TOTAL_MOVED"
echo ""
echo "各文件夹分布:"
for folder in "${FOLDERS[@]}"; do
    count="${STATS["$folder"]:-0}"
    if [[ "$count" -gt 0 ]]; then
        printf "  %-30s %4d 个\n" "$folder/" "$count"
    fi
done

# 清理统计
clean_count="${STATS["(清理空目录)"]:-0}"
if [[ "$clean_count" -gt 0 ]]; then
    echo "  (清理空目录)                     $clean_count 个"
fi

echo ""
info "根目录剩余文件:"
REMAINING=$(find . -maxdepth 1 -type f 2>/dev/null | wc -l)
echo "  $REMAINING 个（含 desktop.ini 等系统文件）"

echo ""
if $DRY_RUN; then
    echo "确认无误后执行: bash ~/ZCodeProject/organize_downloads.sh --run"
fi
echo "Done!"
