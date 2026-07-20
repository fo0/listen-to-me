"""Render the application icon as a multi-size .ico (used by the CI build)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from listen_to_me.icons import mic_image  # noqa: E402


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "build/icon.ico")
    out.parent.mkdir(parents=True, exist_ok=True)
    image = mic_image("app", 256)
    image.save(
        out,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
