from __future__ import annotations

import os
from html import escape
from typing import Any, List

from qwen_agent.gui.utils import convert_history_to_chatbot
from qwen_agent.llm.schema import Message

from .web_ui import WebUI


H5_PAGE_JS = r"""
() => {
  const removeFooter = () => {
    document.querySelectorAll('footer').forEach((element) => element.remove());
  };
  removeFooter();
  const observer = new MutationObserver(removeFooter);
  observer.observe(document.body, { childList: true, subtree: true });
  return [];
}
"""


class H5WebUI(WebUI):
    """Mobile-first chat page with no agent sidebar or plugin controls."""

    def run(
        self,
        messages: List[Message] | None = None,
        share: bool = False,
        server_name: str | None = None,
        server_port: int | None = None,
        concurrency_limit: int = 10,
        **kwargs: Any,
    ) -> Any:
        self.run_kwargs = kwargs

        from qwen_agent.gui.gradio_dep import gr, mgr, ms

        theme = gr.themes.Default(
            primary_hue=gr.themes.utils.colors.sky,
            neutral_hue=gr.themes.utils.colors.slate,
            radius_size=gr.themes.utils.sizes.radius_lg,
        )
        css_path = os.path.join(os.path.dirname(__file__), "assets", "appH5.css")

        with gr.Blocks(css_paths=css_path, theme=theme, js=H5_PAGE_JS) as demo:
            history = gr.State([])
            with ms.Application():
                with gr.Column(elem_classes="h5-shell"):
                    if self.header_title:
                        gr.HTML(
                            '<header class="h5-header">'
                            '<div class="h5-header__text">'
                            f'<h1>{escape(self.header_title)}</h1>'
                            f'<p>{escape(self.header_subtitle)}</p>'
                            "</div>"
                            "</header>"
                        )

                    chatbot = mgr.Chatbot(
                        value=convert_history_to_chatbot(messages=messages),
                        avatar_images=[self.user_config, self.agent_config_list],
                        height=640,
                        avatar_image_width=48,
                        flushing=False,
                        show_copy_button=True,
                        elem_classes="h5-chatbot",
                    )

                    with gr.Column(elem_classes="h5-composer"):
                        input_box = mgr.MultimodalInput(
                            placeholder=self.input_placeholder,
                            sources=[],
                        )
                        with gr.Column(
                            visible=bool(self.prompt_suggestions),
                            elem_classes="h5-suggestions",
                        ):
                            if self.prompt_suggestions:
                                gr.Examples(
                                    label="快捷提问",
                                    examples=self.prompt_suggestions[:3],
                                    inputs=[input_box],
                                )

                    audio_input = gr.State(None)
                    input_promise = input_box.submit(
                        fn=self.add_text,
                        inputs=[input_box, audio_input, chatbot, history],
                        outputs=[input_box, audio_input, chatbot, history],
                        queue=False,
                    )
                    input_promise = input_promise.then(
                        self.agent_run,
                        [chatbot, history],
                        [chatbot, history],
                    )
                    input_promise.then(self.flushed, None, [input_box])

            demo.load(None)

        demo.queue(default_concurrency_limit=concurrency_limit).launch(
            share=share,
            server_name=server_name,
            server_port=server_port,
        )
        return demo
