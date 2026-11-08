#!/bin/sh
# .githooks/_guard.sh —— 逻辑都在这；三个入口只 source 它
MAIN=main

_branch()  { git symbolic-ref --short -q HEAD 2>/dev/null || git rev-parse --abbrev-ref HEAD 2>/dev/null; }
_gitdir()  { git rev-parse --git-dir; }
_marker()  { printf '%s/return-branch' "$(_gitdir)"; }
_issue()   { printf '%s' "$1" | sed -n 's/^\(I-[0-9][0-9]*\)-.*/\1/p'; }

# 属于 main 的文档：docs/ 全部、AGENTS.md，以及仓库自身的配置
_is_doc() {
  case "$1" in
    docs/*|AGENTS.md|.gitignore|.gitattributes|.githooks/*) return 0 ;;
  esac
  return 1
}

guard_checkout() {          # post-checkout "$@"
  [ "$3" = "1" ] || return 0
  prev=$(git rev-parse --abbrev-ref '@{-1}' 2>/dev/null) || prev=""
  cur=$(_branch)
  [ -z "$prev" ] && return 0
  if [ "$cur" = "$MAIN" ] && [ "$prev" != "$MAIN" ]; then
    printf '%s\n' "$prev" > "$(_marker)"
    echo "回程护栏：已离开 $prev，停在 $MAIN。" >&2
    echo "  改完文档、提交、推送后必须回程：git switch - && git merge $MAIN" >&2
  elif [ "$cur" != "$MAIN" ]; then
    rm -f "$(_marker)"
    if ! git merge-base --is-ancestor "$MAIN" HEAD 2>/dev/null; then
      echo "回程护栏：$cur 还落后 $MAIN，先 git merge $MAIN 再继续。" >&2
    fi
  fi
}

guard_pre_commit() {
  [ -e "$(_gitdir)/MERGE_HEAD" ] && return 0
  [ -e "$(_gitdir)/CHERRY_PICK_HEAD" ] && return 0
  # 还没有任何 issue 分支时放行：建仓的第一次提交就在 main 上，可能带代码
  git for-each-ref --format='%(refname:short)' refs/heads | grep -q '^I-' || return 0
  cur=$(_branch)
  files=$(git diff --cached --name-only)
  [ -z "$files" ] && return 0
  if [ "$cur" = "$MAIN" ]; then
    for f in $files; do
      _is_doc "$f" && continue
      echo "回程护栏：$f 不属于 $MAIN——代码和本 issue 的文件提交在 issue 分支上。" >&2
      echo "  先 git switch - 回到你的分支，再提交。" >&2
      return 1
    done
  else
    id=$(_issue "$cur")
    for f in $files; do
      _is_doc "$f" || continue
      [ -n "$id" ] && [ "$f" = "docs/issues/$id.md" ] && continue
      echo "回程护栏：$f 属于 $MAIN，不该在 $cur 上提交。" >&2
      echo "  先在分支提交手上的代码 → git switch $MAIN → 改文档并提交 → git switch - && git merge $MAIN" >&2
      return 1
    done
  fi
  return 0
}

guard_post_commit() {
  cur=$(_branch)
  [ "$cur" = "$MAIN" ] || return 0
  [ -f "$(_marker)" ] || return 0
  echo "回程护栏：文档已落在 $MAIN。现在回程：git switch - && git merge $MAIN" >&2
}
