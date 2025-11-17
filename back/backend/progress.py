def make_tqdm_line(total: int, current: int, stage: str) -> str:
    current = min(current, total)
    pct = int((current / total) * 100) if total else 100
    blocks = int(pct / 4)
    bar = "█" * blocks + ("▎" if (pct % 4) >= 2 else "")
    bar = bar.ljust(25, ".")
    return f"{stage} {pct}%|{bar}| {current}/{total}"