# Copyright 2023 The Qwen team, Alibaba Group. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
from http import HTTPStatus
from pprint import pformat
from typing import Any, Dict, Iterator, List, Optional

import dashscope

from qwen_agent.llm.base import ModelServiceError, register_llm
from qwen_agent.llm.function_calling import BaseFnCallModel
from qwen_agent.llm.schema import ASSISTANT, FunctionCall, Message
from qwen_agent.log import logger


def _get_dashscope_field(response: Any, field: str, default: Any = None) -> Any:
    if isinstance(response, dict):
        return response.get(field, default)
    return getattr(response, field, default)


def _get_dashscope_request_id(response: Any) -> Any:
    request_id = _get_dashscope_field(response, 'request_id')
    if request_id:
        return request_id
    request_id = _get_dashscope_field(response, 'requestId')
    if request_id:
        return request_id
    headers = _get_dashscope_field(response, 'headers', {}) or {}
    if isinstance(headers, dict):
        return headers.get('x-request-id') or headers.get('X-Request-Id')
    return None


def _log_dashscope_error(response: Any, context: Dict[str, Any]) -> None:
    logger.warning(
        'DashScope model call failed model=%s stream=%s delta_stream=%s status_code=%s '
        'code=%s message=%s request_id=%s chunk_index=%s received_chunks=%s',
        context.get('model', 'unknown'),
        context.get('stream', 'unknown'),
        context.get('delta_stream', 'unknown'),
        _get_dashscope_field(response, 'status_code', 'unknown'),
        _get_dashscope_field(response, 'code', 'unknown'),
        _get_dashscope_field(response, 'message', 'unknown'),
        _get_dashscope_request_id(response) or 'unknown',
        context.get('chunk_index', 'n/a'),
        context.get('received_chunks', 'n/a'),
    )


def _log_dashscope_exception(exc: BaseException, context: Dict[str, Any]) -> None:
    logger.warning(
        'DashScope model call raised model=%s stream=%s delta_stream=%s message_count=%s '
        'chunk_index=%s received_chunks=%s exception_type=%s exception_message=%s',
        context.get('model', 'unknown'),
        context.get('stream', 'unknown'),
        context.get('delta_stream', 'unknown'),
        context.get('message_count', 'n/a'),
        context.get('chunk_index', 'n/a'),
        context.get('received_chunks', 'n/a'),
        type(exc).__name__,
        str(exc) or repr(exc),
        exc_info=True,
    )


@register_llm('qwen_dashscope')
class QwenChatAtDS(BaseFnCallModel):

    def __init__(self, cfg: Optional[Dict] = None):
        super().__init__(cfg)
        self.model = self.model or 'qwen-max'
        initialize_dashscope(cfg)

    def _chat_stream(
        self,
        messages: List[Message],
        delta_stream: bool,
        generate_cfg: dict,
    ) -> Iterator[List[Message]]:
        messages = [msg.model_dump() for msg in messages]
        if messages[-1]['role'] == ASSISTANT:
            messages[-1]['partial'] = True
        messages = self._conv_qwen_agent_messages_to_oai(messages)
        logger.debug(f'LLM Input: \n{pformat(messages, indent=2)}')
        logger.debug(f'LLM Input generate_cfg: \n{generate_cfg}')
        try:
            response = dashscope.Generation.call(
                self.model,
                messages=messages,  # noqa
                result_format='message',
                stream=True,
                **generate_cfg)
        except Exception as exc:
            _log_dashscope_exception(exc, {
                'model': self.model,
                'stream': True,
                'delta_stream': delta_stream,
                'message_count': len(messages),
            })
            raise ModelServiceError(exception=exc) from exc
        context = {
            'model': self.model,
            'stream': True,
            'delta_stream': delta_stream,
        }
        if delta_stream:
            return self._delta_stream_output(response, context=context)
        else:
            return self._full_stream_output(response, context=context)

    def _chat_no_stream(
        self,
        messages: List[Message],
        generate_cfg: dict,
    ) -> List[Message]:
        messages = [msg.model_dump() for msg in messages]
        if messages[-1]['role'] == ASSISTANT:
            messages[-1]['partial'] = True
        messages = self._conv_qwen_agent_messages_to_oai(messages)
        logger.debug(f'LLM Input: \n{pformat(messages, indent=2)}')
        try:
            response = dashscope.Generation.call(
                self.model,
                messages=messages,  # noqa
                result_format='message',
                stream=False,
                **generate_cfg)
        except Exception as exc:
            _log_dashscope_exception(exc, {
                'model': self.model,
                'stream': False,
                'delta_stream': False,
                'message_count': len(messages),
            })
            raise ModelServiceError(exception=exc) from exc
        if response.status_code == HTTPStatus.OK:
            return [
                Message(role=ASSISTANT,
                        content=response.output.choices[0].message.content,
                        reasoning_content=response.output.choices[0].message.get('reasoning_content', ''),
                        extra={'model_service_info': response})
            ]
        else:
            _log_dashscope_error(response, {
                'model': self.model,
                'stream': False,
                'delta_stream': False,
            })
            raise ModelServiceError(code=response.code,
                                    message=response.message,
                                    extra={'model_service_info': response})

    def _continue_assistant_response(
        self,
        messages: List[Message],
        generate_cfg: dict,
        stream: bool,
    ) -> Iterator[List[Message]]:
        return self._chat(messages, stream=stream, delta_stream=False, generate_cfg=generate_cfg)

    @staticmethod
    def _delta_stream_output(response, context: Optional[Dict[str, Any]] = None) -> Iterator[List[Message]]:
        context = context or {}
        received_chunks = 0
        try:
            for chunk_index, chunk in enumerate(response):
                if chunk.status_code == HTTPStatus.OK:
                    received_chunks += 1
                    yield [
                        Message(role=ASSISTANT,
                                content=chunk.output.choices[0].message.content,
                                reasoning_content=chunk.output.choices[0].message.reasoning_content,
                                extra={'model_service_info': chunk})
                    ]
                else:
                    error_context = dict(context)
                    error_context.update(chunk_index=chunk_index, received_chunks=received_chunks)
                    _log_dashscope_error(chunk, error_context)
                    raise ModelServiceError(code=chunk.code, message=chunk.message, extra={'model_service_info': chunk})
        except ModelServiceError:
            raise
        except Exception as exc:
            error_context = dict(context)
            error_context.update(chunk_index=received_chunks, received_chunks=received_chunks)
            _log_dashscope_exception(exc, error_context)
            raise ModelServiceError(exception=exc) from exc

    @staticmethod
    def _full_stream_output(response, context: Optional[Dict[str, Any]] = None) -> Iterator[List[Message]]:
        context = context or {}
        full_content = ''
        full_reasoning_content = ''
        full_tool_calls = []
        received_chunks = 0
        try:
            for chunk_index, chunk in enumerate(response):
                if chunk.status_code == HTTPStatus.OK:
                    received_chunks += 1
                    if chunk.output.choices[0].message.get('reasoning_content', ''):
                        full_reasoning_content += chunk.output.choices[0].message.reasoning_content
                    if chunk.output.choices[0].message.content:
                        full_content += chunk.output.choices[0].message.content
                    tool_calls = chunk.output.choices[0].message.get('tool_calls', None)
                    if tool_calls:
                        for tc in tool_calls:
                            if full_tool_calls and (not tc['id'] or
                                                    tc['id'] == full_tool_calls[-1]['extra']['function_id']):
                                if tc['function'].get('name', ''):
                                    full_tool_calls[-1].function_call['name'] += tc['function']['name']
                                if tc['function'].get('arguments', ''):
                                    full_tool_calls[-1].function_call['arguments'] += tc['function']['arguments']
                            else:
                                full_tool_calls.append(
                                    Message(role=ASSISTANT,
                                            content='',
                                            function_call=FunctionCall(name=tc['function'].get('name', ''),
                                                                       arguments=tc['function'].get('arguments', '')),
                                            extra={
                                                'model_service_info': json.loads(str(chunk)),
                                                'function_id': tc['id']
                                            }))
                    res = []
                    if full_reasoning_content:
                        res.append(
                            Message(role=ASSISTANT,
                                    content='',
                                    reasoning_content=full_reasoning_content,
                                    extra={
                                        'model_service_info': json.loads(str(chunk)),
                                    }))
                    if full_content:
                        res.append(
                            Message(role=ASSISTANT,
                                    content=full_content,
                                    extra={
                                        'model_service_info': json.loads(str(chunk)),
                                    }))
                    if full_tool_calls:
                        res += full_tool_calls
                    yield res
                else:
                    error_context = dict(context)
                    error_context.update(chunk_index=chunk_index, received_chunks=received_chunks)
                    _log_dashscope_error(chunk, error_context)
                    raise ModelServiceError(code=chunk.code, message=chunk.message, extra={'model_service_info': chunk})
        except ModelServiceError:
            raise
        except Exception as exc:
            error_context = dict(context)
            error_context.update(chunk_index=received_chunks, received_chunks=received_chunks)
            _log_dashscope_exception(exc, error_context)
            raise ModelServiceError(exception=exc) from exc


def initialize_dashscope(cfg: Optional[Dict] = None) -> None:
    cfg = cfg or {}

    api_key = cfg.get('api_key', '')
    base_http_api_url = cfg.get('base_http_api_url', None)
    base_websocket_api_url = cfg.get('base_websocket_api_url', None)

    if not api_key:
        api_key = os.getenv('DASHSCOPE_API_KEY', 'EMPTY')
    if not base_http_api_url:
        base_http_api_url = os.getenv('DASHSCOPE_HTTP_URL', None)
    if not base_websocket_api_url:
        base_websocket_api_url = os.getenv('DASHSCOPE_WEBSOCKET_URL', None)

    api_key = api_key.strip()
    if api_key in ('', 'EMPTY'):
        if dashscope.api_key is None or dashscope.api_key in ('', 'EMPTY'):
            logger.warning(
                'No valid dashscope api_key found in cfg, environment variable `DASHSCOPE_API_KEY` or dashscope.api_key, the model call may raise errors.'
            )
        else:
            logger.info('No dashscope api_key found in cfg, using the dashscope.api_key that has already been set.')
    else:  # valid api_key
        if api_key != dashscope.api_key:
            logger.info('Setting the dashscope api_key.')
            dashscope.api_key = api_key
        # or do nothing since both keys are the same

    if base_http_api_url is not None:
        dashscope.base_http_api_url = base_http_api_url.strip()
    if base_websocket_api_url is not None:
        dashscope.base_websocket_api_url = base_websocket_api_url.strip()
