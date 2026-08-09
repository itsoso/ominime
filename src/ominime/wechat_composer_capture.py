"""Local pre-submit text recovery for the WeChat desktop client."""

from .kim_composer_capture import (
    CapturedFrame,
    KimPreSubmitCapture,
    NormalizedRect,
)


WECHAT_BUNDLE_ID = "com.tencent.xinWeChat"
WECHAT_COMPOSER_LEFT_POINTS = 305
WECHAT_COMPOSER_RIGHT_POINTS = 8
WECHAT_COMPOSER_BOTTOM_POINTS = 6
WECHAT_COMPOSER_TOP_POINTS = 141
WECHAT_COMPOSER_ROI = NormalizedRect(
    x=WECHAT_COMPOSER_LEFT_POINTS / 880,
    y=WECHAT_COMPOSER_BOTTOM_POINTS / 640,
    width=(
        880 - WECHAT_COMPOSER_LEFT_POINTS - WECHAT_COMPOSER_RIGHT_POINTS
    ) / 880,
    height=(
        WECHAT_COMPOSER_TOP_POINTS - WECHAT_COMPOSER_BOTTOM_POINTS
    ) / 640,
)


class WeChatPreSubmitCapture(KimPreSubmitCapture):
    """Freeze and locally recognize the visible WeChat composer."""

    composer_roi = WECHAT_COMPOSER_ROI
    failure_prefix = "wechat_ocr"

    def composer_roi_for_frame(self, frame: CapturedFrame) -> NormalizedRect:
        return NormalizedRect(
            x=WECHAT_COMPOSER_LEFT_POINTS / frame.width,
            y=WECHAT_COMPOSER_BOTTOM_POINTS / frame.height,
            width=(
                frame.width
                - WECHAT_COMPOSER_LEFT_POINTS
                - WECHAT_COMPOSER_RIGHT_POINTS
            ) / frame.width,
            height=(
                WECHAT_COMPOSER_TOP_POINTS
                - WECHAT_COMPOSER_BOTTOM_POINTS
            ) / frame.height,
        )
