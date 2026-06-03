"""评测缓存标记脚本。
Makefile 用它记录某个评测 step 已完成，避免重复跑。

用法:
  python -m scripts.mark_eval_done.py <cache_dir> <step_name>
"""
import sys
from pathlib import Path

def main():
    if len(sys.argv) < 3:
        print("用法: mark_eval_done.py <cache_dir> <step_name>")
        sys.exit(1)

    cache_dir = Path(sys.argv[1])
    step = sys.argv[2]
    cache_dir.mkdir(parents=True, exist_ok=True)
    done_file = cache_dir / f"{step}.done"
    done_file.write_text("done", encoding="utf-8")
    print(f"  [缓存] {step} 完成标记已写入 {done_file}")

if __name__ == "__main__":
    main()
