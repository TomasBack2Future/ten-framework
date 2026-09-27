#
# This file is part of TEN Framework, an open source project.
# Licensed under the Apache License, Version 2.0.
# See the LICENSE file for more information.
#
import os
from pathlib import Path

from ten_runtime import App, TenEnv, LogLevel


class DefaultApp(App):

    def on_configure(self, ten_env: TenEnv):
        ten_env.log(LogLevel.DEBUG, "on_init")
        property_file = os.environ.get("JEV_PROPERTY_FILE")
        if property_file:
            error = ten_env.init_property_from_json(
                Path(property_file).read_text()
            )
            if error:
                raise ValueError("invalid session graph")
        ten_env.on_configure_done()

    def on_init(self, ten_env: TenEnv):
        ten_env.on_init_done()

    def on_deinit(self, ten_env: TenEnv) -> None:
        ten_env.log(LogLevel.DEBUG, "on_deinit")
        ten_env.on_deinit_done()


if __name__ == "__main__":

    app = DefaultApp()
    print("app created.")

    app.run(False)
    print("app run completed.")
