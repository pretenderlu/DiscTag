from disctag import i18n
from disctag.settings import load_settings

# 语言必须在导入界面模块之前确定：部分界面文字在导入时生成。
i18n.set_language(i18n.resolve(load_settings().get("language", "auto")))

from disctag.app import DiscTagApp  # noqa: E402


if __name__ == "__main__":
    DiscTagApp().run()
