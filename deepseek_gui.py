# deepseek_gui.py
import os
import sys
from typing import List, Dict, Any

from dotenv import load_dotenv
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QDoubleSpinBox, QSpinBox, QCheckBox, QPlainTextEdit, QTextBrowser,
    QMessageBox, QGroupBox, QFormLayout, QLineEdit
)

from deepseek_client import DeepSeekConfig, DeepSeekClient


# -------------------------
# 后台线程：避免 GUI 卡死
# -------------------------
class ChatWorker(QThread):
    finished = Signal(dict)         # resp json
    failed = Signal(str)            # error message

    def __init__(self, client: DeepSeekClient, messages: List[Dict[str, str]], model: str,
                 temperature: float, top_p: float, max_tokens: int, show_reasoning: bool):
        super().__init__()
        self.client = client
        self.messages = messages
        self.model = model
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        self.show_reasoning = show_reasoning

    def run(self):
        try:
            resp = self.client.chat(
                self.messages,
                model=self.model,
                temperature=self.temperature,
                top_p=self.top_p,
                max_tokens=self.max_tokens,
            )
            self.finished.emit(resp)
        except Exception as e:
            self.failed.emit(str(e))


# -------------------------
# GUI 主窗口
# -------------------------
class DeepSeekChatGUI(QWidget):
    def __init__(self):
        super().__init__()
        load_dotenv()

        self.setWindowTitle("DeepSeek GUI Chat (Multi-turn Demo)")
        self.resize(980, 680)

        # ---- 读取 key ----
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            # GUI 里给个更友好的报错
            QMessageBox.critical(self, "Missing API Key",
                                 "没有检测到环境变量 DEEPSEEK_API_KEY。\n"
                                 "请先在终端 export DEEPSEEK_API_KEY=... 或在 .env 中设置。")
            raise RuntimeError("Missing DEEPSEEK_API_KEY")

        # ---- client 固定：底层只初始化一次 ----
        self.cfg = DeepSeekConfig(api_key=api_key)
        self.client = DeepSeekClient(self.cfg)

        # ---- 多轮对话记忆栈 ----
        self.messages: List[Dict[str, str]] = []
        self.total_usage: Dict[str, int] = {}

        # ---- UI ----
        root = QHBoxLayout(self)

        # 左侧：设置面板
        left = QVBoxLayout()
        left.addWidget(self._build_settings_panel())
        left.addStretch(1)

        # 右侧：聊天区
        right = QVBoxLayout()
        right.addWidget(self._build_chat_panel())

        root.addLayout(left, 0)
        root.addLayout(right, 1)

        # 初始 system
        self._apply_system()

        # 预加载模型列表（失败也不致命）
        self._refresh_models_silent()

    # ---------- UI building ----------
    def _build_settings_panel(self) -> QWidget:
        box = QGroupBox("Settings")
        layout = QFormLayout(box)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.addItems(["deepseek-chat", "deepseek-reasoner"])
        layout.addRow(QLabel("Model:"), self.model_combo)

        self.btn_refresh_models = QPushButton("Refresh Models")
        self.btn_refresh_models.clicked.connect(self.on_refresh_models)
        layout.addRow(self.btn_refresh_models)

        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setSingleStep(0.05)
        self.temp_spin.setValue(0.7)
        layout.addRow(QLabel("Temperature:"), self.temp_spin)

        self.top_p_spin = QDoubleSpinBox()
        self.top_p_spin.setRange(0.0, 1.0)
        self.top_p_spin.setSingleStep(0.05)
        self.top_p_spin.setValue(0.9)
        layout.addRow(QLabel("Top_p:"), self.top_p_spin)

        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(1, 8000)
        self.max_tokens_spin.setValue(1200)
        layout.addRow(QLabel("Max tokens:"), self.max_tokens_spin)

        self.keep_turns_spin = QSpinBox()
        self.keep_turns_spin.setRange(1, 200)
        self.keep_turns_spin.setValue(20)
        layout.addRow(QLabel("Keep turns:"), self.keep_turns_spin)

        self.show_usage_chk = QCheckBox("Show usage each turn")
        self.show_usage_chk.setChecked(True)
        layout.addRow(self.show_usage_chk)

        self.show_reasoning_chk = QCheckBox("Show reasoning_content (if present)")
        self.show_reasoning_chk.setChecked(False)
        layout.addRow(self.show_reasoning_chk)

        self.system_edit = QPlainTextEdit()
        self.system_edit.setPlaceholderText("System prompt（背景提示词），可随时修改。留空=无 system。")
        self.system_edit.setPlainText("你是一个严谨但不无聊的计算机导师。回答要结构清晰，必要时给例子。")
        self.system_edit.textChanged.connect(self.on_system_changed)
        layout.addRow(QLabel("System:"), self.system_edit)

        self.btn_reset = QPushButton("Reset Chat")
        self.btn_reset.clicked.connect(self.on_reset_chat)
        layout.addRow(self.btn_reset)

        return box

    def _build_chat_panel(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)

        self.chat_view = QTextBrowser()
        self.chat_view.setOpenExternalLinks(False)
        self.chat_view.setPlaceholderText("对话将显示在这里…")
        layout.addWidget(self.chat_view, 1)

        self.status_line = QLineEdit()
        self.status_line.setReadOnly(True)
        self.status_line.setPlaceholderText("status…")
        layout.addWidget(self.status_line)

        bottom = QHBoxLayout()
        self.input_box = QPlainTextEdit()
        self.input_box.setPlaceholderText("在这里输入你的问题…（Ctrl+Enter 发送，Enter 换行）")
        self.input_box.setFixedHeight(90)
        bottom.addWidget(self.input_box, 1)

        self.btn_send = QPushButton("Send (Ctrl+Enter)")
        self.btn_send.clicked.connect(self.on_send)
        bottom.addWidget(self.btn_send, 0)

        layout.addLayout(bottom)

        return wrap

    # ---------- helpers ----------
    def _apply_system(self):
        sys_text = self.system_edit.toPlainText().strip()
        if sys_text:
            if self.messages and self.messages[0].get("role") == "system":
                self.messages[0]["content"] = sys_text
            else:
                self.messages.insert(0, {"role": "system", "content": sys_text})
        else:
            if self.messages and self.messages[0].get("role") == "system":
                self.messages.pop(0)

    def _trim_history(self):
        keep_turns = max(1, int(self.keep_turns_spin.value()))
        max_non_system = keep_turns * 2  # user+assistant per turn

        if self.messages and self.messages[0].get("role") == "system":
            sys_msg = self.messages[0]
            non_sys = self.messages[1:]
            if len(non_sys) > max_non_system:
                non_sys = non_sys[-max_non_system:]
            self.messages = [sys_msg] + non_sys
        else:
            if len(self.messages) > max_non_system:
                self.messages = self.messages[-max_non_system:]

    def _append_chat(self, who: str, text: str):
        # 简单做点格式区分
        safe = (text or "").replace("<", "&lt;").replace(">", "&gt;")
        if who == "You":
            self.chat_view.append(f"<b>You&gt;</b> {safe}")
        else:
            self.chat_view.append(f"<b>AI&gt;</b> {safe}")
        self.chat_view.verticalScrollBar().setValue(self.chat_view.verticalScrollBar().maximum())

    def _usage_line(self, resp: dict) -> str:
        usage = resp.get("usage")
        if not usage:
            return "(no usage field)"
        return "  ".join([f"{k}={v}" for k, v in usage.items()])

    def _accumulate_usage(self, resp: dict):
        u = resp.get("usage", {})
        for k, v in u.items():
            if isinstance(v, int):
                self.total_usage[k] = self.total_usage.get(k, 0) + v

    # ---------- events ----------
    def on_system_changed(self):
        # 实时更新 system（不清空历史）
        self._apply_system()

    def on_reset_chat(self):
        # 保留 system，清空对话
        sys_text = self.messages[0]["content"] if (self.messages and self.messages[0].get("role") == "system") else ""
        self.messages = []
        if sys_text:
            self.messages.append({"role": "system", "content": sys_text})
        self.total_usage = {}
        self.chat_view.clear()
        self.status_line.setText("reset ok")

    def on_refresh_models(self):
        try:
            data = self.client.list_models()
            ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
            if ids:
                cur = self.model_combo.currentText().strip()
                self.model_combo.clear()
                self.model_combo.addItems(ids)
                # 尽量保持当前选择
                if cur:
                    idx = self.model_combo.findText(cur)
                    if idx >= 0:
                        self.model_combo.setCurrentIndex(idx)
                self.status_line.setText(f"models refreshed: {len(ids)}")
            else:
                self.status_line.setText("models refreshed, but empty")
        except Exception as e:
            QMessageBox.warning(self, "Refresh Models Failed", str(e))

    def _refresh_models_silent(self):
        try:
            data = self.client.list_models()
            ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
            if ids:
                cur = self.model_combo.currentText().strip()
                self.model_combo.clear()
                self.model_combo.addItems(ids)
                if cur:
                    idx = self.model_combo.findText(cur)
                    if idx >= 0:
                        self.model_combo.setCurrentIndex(idx)
        except Exception:
            pass

    def keyPressEvent(self, event):
        # Ctrl+Enter 发送；Enter 换行（符合你“聊天输入框”的手感）
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and (event.modifiers() & Qt.ControlModifier):
            self.on_send()
            return
        super().keyPressEvent(event)

    def on_send(self):
        text = self.input_box.toPlainText().strip()
        if not text:
            return

        self.input_box.clear()
        self._append_chat("You", text)

        # 更新 system + 历史裁剪
        self._apply_system()
        self.messages.append({"role": "user", "content": text})
        self._trim_history()

        # UI 状态
        self.btn_send.setEnabled(False)
        self.status_line.setText("thinking…")

        # 后台线程请求
        model = self.model_combo.currentText().strip() or "deepseek-chat"
        worker = ChatWorker(
            client=self.client,
            messages=list(self.messages),  # 传拷贝，避免并发改动
            model=model,
            temperature=float(self.temp_spin.value()),
            top_p=float(self.top_p_spin.value()),
            max_tokens=int(self.max_tokens_spin.value()),
            show_reasoning=self.show_reasoning_chk.isChecked(),
        )
        worker.finished.connect(self.on_response)
        worker.failed.connect(self.on_error)
        worker.start()

        self._worker = worker  # 防止被 gc

    def on_response(self, resp: dict):
        try:
            msg = resp["choices"][0]["message"]
            content = msg.get("content", "") or ""
            self._append_chat("AI", content)

            # 更新 messages（多轮）
            self.messages.append({"role": "assistant", "content": content})

            # reasoning_content（可选展示）
            if self.show_reasoning_chk.isChecked() and msg.get("reasoning_content"):
                self.chat_view.append("<i>[reasoning_content]</i>")
                self.chat_view.append((msg["reasoning_content"] or "").replace("<", "&lt;").replace(">", "&gt;"))

            # usage（每轮 + 累计）
            if self.show_usage_chk.isChecked():
                self._accumulate_usage(resp)
                usage_line = self._usage_line(resp)
                total_line = "  ".join([f"{k}={v}" for k, v in self.total_usage.items()]) if self.total_usage else ""
                self.chat_view.append(f"<span style='color:gray'>[usage] {usage_line}</span>")
                if total_line:
                    self.chat_view.append(f"<span style='color:gray'>[total] {total_line}</span>")

            self.status_line.setText("ok")
        finally:
            self.btn_send.setEnabled(True)

    def on_error(self, err: str):
        self.status_line.setText("error")
        self.btn_send.setEnabled(True)
        QMessageBox.warning(self, "Request Failed", err)


def main():
    app = QApplication(sys.argv)
    w = DeepSeekChatGUI()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
