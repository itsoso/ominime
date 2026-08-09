"""Local pre-submit text recovery for the WeChat desktop client."""

from .kim_composer_capture import KimPreSubmitCapture, NormalizedRect


WECHAT_BUNDLE_ID = "com.tencent.xinWeChat"
WECHAT_COMPOSER_ROI = NormalizedRect(
    x=0.35,
    y=0.01,
    width=0.63,
    height=0.21,
)


class WeChatPreSubmitCapture(KimPreSubmitCapture):
    """Freeze and locally recognize the visible WeChat composer."""

    composer_roi = WECHAT_COMPOSER_ROI
    failure_prefix = "wechat_ocr"
