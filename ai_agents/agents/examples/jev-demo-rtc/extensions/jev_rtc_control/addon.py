from ten_runtime import Addon, register_addon_as_extension
from .extension import JevRTCControl


@register_addon_as_extension("jev_rtc_control")
class RTCAddon(Addon):
    def on_create_instance(self, ten_env, name, context):
        ten_env.on_create_instance_done(JevRTCControl(name), context)
