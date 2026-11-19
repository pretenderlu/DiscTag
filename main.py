from disctag import i18n
from disctag.settings import load_settings

# 在导入界面模块之前确定语言。模块导入时不再生成界面文字，此顺序只是保持简单、稳妥。
i18n.set_language(i18n.resolve(load_settings().get("language", "auto")))

from disctag.app import DiscTagApp  # noqa: E402


if __name__ == "__main__":
    DiscTagApp().run()
