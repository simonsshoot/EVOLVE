import json
import os
import docker
import struct
import socket
import re
import logging
import tarfile
from typing import Any, Callable, List, Dict
import io
from configs import setup_logger


class Container:
    def __init__(self):
        self.client = docker.from_env()
        self.container: docker.models.containers.Container = self.client.containers.run(
            "ubuntu",
            detach=True,
            tty=True,
            stdin_open=True,
            remove=True,
            labels={"created_by": "os-pipeline"},
        )
        self.exec_id = self.client.api.exec_create(
            self.container.id, "bash --login", stdin=True, tty=True
        )["Id"]
        self.sock = self.client.api.exec_start(self.exec_id, socket=True)._sock
        self.sock.settimeout(5)
        # Install Python in the container
        # self._send_command("apt update && apt install -y python3 python3-pip")
        # Clear buffer
        self.sock.recv(1000)
        self.logger = setup_logger("container_logger")

    def __del__(self):
        try:
            self.container.stop()
        except:
            self.logger.warning("Container stopped unexpectedly.")

    def _send_command(self, command: str):
        self.sock.send(command.encode("utf-8") + b"\n")
        data = self.sock.recv(8)
        _, n = struct.unpack(">BxxxL", data)
        self.sock.recv(n)

    def execute_init(self, command: str, user: str) -> str:
        cmd = ["bash", "-c", command]
        return self.container.exec_run(cmd, user=user)

    def execute(self, command: str, user: str) -> str:
        """通过socket套接字与远程shell进行通信,模拟真实终端行为的环境，执行会产生持续输出的交互式命令"""

        class DummyOutput:
            output: bytes
            exit_code: int

            def __init__(self, code, o):
                self.output = o
                self.exit_code = code

        if not isinstance(command, str):
            return DummyOutput(-1, b"")

        self._send_command(command)
        output = b""
        while True:
            try:
                data = self.sock.recv(8)
                if not data:
                    break
                _, n = struct.unpack(">BxxxL", data)
                line = self.sock.recv(n)
                output += line
                if re.search(b"\x1b.+@.+[#|$] ", line):
                    break
            except (TimeoutError, socket.timeout):
                break
        return DummyOutput(0, output)

    def put_file(self, file_content: str, file_name: str):
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode="w") as tar:
            file_data = io.BytesIO(file_content.encode("utf-8"))
            tar_info = tarfile.TarInfo(name=file_name)
            tar_info.size = len(file_content.encode("utf-8"))
            tar.addfile(tarinfo=tar_info, fileobj=file_data)

        tar_stream.seek(0)
        self.container.put_archive("/tmp", tar_stream)

    def run_file(self, file_path: str, user: str) -> str:
        result = self.container.exec_run(f"python3 {file_path}", user=user)
        return result

    def install_packages(self, packages: list, user: str = "root") -> bool:
        """安装 Python 包"""
        if not packages:
            return True

        builtin_modules = {
            "re",
            "os",
            "sys",
            "json",
            "datetime",
            "collections",
            "itertools",
            "math",
            "time",
            "random",
        }
        packages_to_install = [pkg for pkg in packages if pkg not in builtin_modules]

        if not packages_to_install:
            self.logger.info(
                f"All packages are built-in modules, skipping installation"
            )
            return True

        self.logger.info(f"Installing packages: {packages_to_install}")

        check_pip = self.container.exec_run("which pip3", user=user)
        if check_pip.exit_code != 0:
            self.logger.info("Installing pip3...")
            install_pip = self.container.exec_run(
                "apt update && apt install -y python3-pip", user=user
            )
            if install_pip.exit_code != 0:
                self.logger.error("Failed to install pip3")
                return False

        packages_str = " ".join(packages_to_install)
        result = self.container.exec_run(f"pip3 install {packages_str}", user=user)

        if result.exit_code == 0:
            self.logger.info(f"Successfully installed packages: {packages_to_install}")
            return True
        else:
            self.logger.error(f"Failed to install packages: {result.output.decode()}")
            return False

    def execute_python_code(
        self,
        code: str,
        function_name: str,
        query: str,
        action: str,
        require: list = None,
        user: str = "root",
    ) -> tuple:
        """
        在容器中执行 Python 代码并返回结果
        Args:
          code: Python 函数代码
          function_name: 函数名称
          query: 要传递给函数的用户请求文本
          action: 要传递给函数的 agent 拟执行动作/操作
          require: 需要导入的模块列表
          user: 执行用户

        Returns:
          (success: bool, result: Any, error: str)
        """
        # 生成 import 语句
        import_lines = ["import json", "import sys"]
        if require:
            for module in require:
                import_lines.append(f"import {module}")
        imports = "\n".join(import_lines)

        query_repr = repr(query)
        action_repr = repr(action)
        full_script = f"""{imports}

{code}

try:
    result = {function_name}({query_repr}, {action_repr})
    print(json.dumps({{"success": True, "result": result, "error": None}}))
except Exception as e:
    print(json.dumps({{"success": False, "result": None, "error": str(e)}}))
    sys.exit(1)
"""

        # 将脚本写入容器
        script_name = f"safety_tool_{function_name}.py"
        self.put_file(full_script, script_name)

        # 执行脚本
        result = self.container.exec_run(f"python3 /tmp/{script_name}", user=user)

        try:
            output = result.output.decode("utf-8").strip()
            self.logger.info(f"Tool execution output: {output}")

            result_data = json.loads(output)
            return (
                result_data.get("success", False),
                result_data.get("result"),
                result_data.get("error"),
            )
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse tool output: {output}")
            return (False, None, f"JSON decode error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Unexpected error: {str(e)}")
            return (False, None, str(e))


class Session:
    def __init__(self, model_inference, history=None) -> None:
        self.history: list[dict] = history or []
        self.exception_raised = False
        self.model_inference = self.wrap_inference(model_inference)

    def inject(self, message: dict) -> None:
        assert isinstance(message, dict)
        assert "role" in message and "content" in message
        assert isinstance(message["role"], str)
        assert isinstance(message["content"], str)
        assert message["role"] in ["user", "agent"]
        self.history.append(message)

    def action(self, extend_messages: List[dict] = None):
        extend = []
        environment = None
        if extend_messages:
            if isinstance(extend_messages, list):
                print("######：" + str(extend_messages))
                extend.extend(extend_messages)
            elif isinstance(extend_messages, dict):
                print("######：" + str(extend_messages))
                extend.append(extend_messages)
            else:
                raise Exception("Invalid extend_messages")
        result = self.model_inference(self.history + extend)
        temp = next(reversed(self.history))
        last_item = ""
        if temp["content"].startswith("The output of the OS"):
            last_item = temp["content"]
        self.history.extend(extend)
        self.history.append({"role": "agent", "content": result})
        print("#####" + last_item)
        return last_item, result

    def wrap_inference(
        self, inference_function: Callable[[List[dict]], str]
    ) -> Callable[[List[dict]], str]:
        def _func(history: List[dict]) -> str:
            if self.exception_raised:
                return ""
            try:
                result = inference_function(history)
            except Exception as e:
                print(e)
                import traceback

                traceback.print_exc()
                print("Warning: Exception raised during inference.")
                self.exception_raised = True
                result = ""
            return result

        return _func
