from __future__ import annotations # 类型注解增强辅助
import os
import json # 把python字典转成JSON字符串,发HTTP请求时要用
import time # 用来重试失败请求前sleep一会儿
from dataclasses import dataclass # 用来写配置类,省掉大量样板代码
from typing import List, Dict, Any, Optional # 类型标注
import sys # 读取命令行参数

import requests # 发送HTTP请求


@dataclass # 装饰器,让类自动生成 __init__ 和 __repr__ 等方法
class DeepSeekConfig:
    """
    DeepSeekClient的配置类
    """
    api_key: str
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = 1024
    timeout_s: int = 60 # 超过时间
    retries: int = 2 # 失败后最多重试几次
    backoff_s: float = 1.5 # 重试等待基准秒数


class DeepSeekClient:
    """
    DeepSeekClient的客户端类
    """
    def __init__(self, cfg: DeepSeekConfig): # __init__是对象创建时自动执行的初始化函数,self代表当前对象自己,cfg是一个DeepSeekConfig对象实例
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json", # 告诉服务器发过去的数据是JSON格式
            "Authorization": f"Bearer {self.cfg.api_key}", # Bearer是HTTP认证中常见的一种token携带方式
        }) # 给这个会话对象设置默认请求头,headers代表HTTP请求头,update({...})是字典的更新方法,整句含义是给上面创建的会话加上认证信息

    def chat(self, messages: List[Dict[str, str]],
             *, # 这个单独的星号表示其后面的参数必须使用"关键字参数"方式传入,不能直接按位置传入
             model: Optional[str] = None,
             temperature: Optional[float] = None,
             top_p: Optional[float] = None,
             max_tokens: Optional[int] = None,
             stream: bool = False) -> Dict[str, Any]: # stream代表是否开启流式读取,也就是是接受完之后一次输出完整返回结果还是边接受边输出返回结果(类gpt)
        """
        返回整包 JSON响应
        """
        # 组装请求体
        payload = {
            "model": model or self.cfg.model, # 前真则前，前假则后
            "messages": messages, # 直接把消息列表放进请求体,不需要转成JSON字符串,requests会帮我们处理
            "temperature": self.cfg.temperature if temperature is None else temperature, # 更严谨,若传入0.0,直接返回None回退
            "top_p": self.cfg.top_p if top_p is None else top_p,
            "max_tokens": self.cfg.max_tokens if max_tokens is None else max_tokens,
            "stream": stream,
        }

        url = f"{self.cfg.base_url}/chat/completions"  # 组装,对应官方 /chat/completions
        last_err = None # 先定义一个变量,用来保存最后一次错误
        for attempt in range(self.cfg.retries + 1): # Python的for循环写法,若retries是2,则attempt会依次是0,1,2,也就是总共尝试3次
            try:
                r = self.session.post(url, data=json.dumps(payload), timeout=self.cfg.timeout_s) # 发POST请求,data=json.dumps(payload)把字典转成JSON字符串,也可更简洁的写作json=payload,requests会自动处理
                if r.status_code >= 400:
                    # 4xx 多半是参数/权限问题；5xx 可能是服务波动
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text}") # 执行完这个之后丢到下面except里被捕获,按照except部分的逻辑继续执行,不在try部分继续往下执行了
                return r.json() # 若成功则直接把响应JSON解析成Python字典返回
            except Exception as e: # 捕获所有常规异常,并将异常对象命名为e
                last_err = e # 保存这次错误,方便最后抛出
                if attempt < self.cfg.retries:
                    time.sleep(self.cfg.backoff_s * (attempt + 1))
                else:
                    raise last_err # 若for循环所有重试全部失败,把最后的异常抛出去

    def list_models(self) -> Dict[str, Any]: 
        # 注意返回的数据格式,返回的是整包JSON响应,结构大概类似于
        # {
        #     "object": "list",
        #     "data": [
        #         {"id": "deepseek-chat", "object": "model"},
        #         {"id": "deepseek-reasoner", "object": "model"}
        #     ]
        # }
        url = f"{self.cfg.base_url}/models"
        r = self.session.get(url, timeout=self.cfg.timeout_s)
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text}")
        return r.json()




def main():
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise RuntimeError("请先设置环境变量 DEEPSEEK_API_KEY")

    cfg = DeepSeekConfig(
        api_key=api_key,
        model="deepseek-chat",
        temperature=0.7,
        top_p=0.9,
        max_tokens=800,
    )

    client = DeepSeekClient(cfg)

    # 如果在命令行里传入的第一个参数是 --list-models,那程序就去调用 list_models(),把模型 id 打印出来,然后立刻结束(return直接结束整个函数,跳过函数后续内容)
    if len(sys.argv) >= 2 and sys.argv[1] == "--list-models": # sys.argv是在命令行运行这个Python文件时输入的命令行参数列表,sys.argv[0]是脚本文件名,sys.argv[1]是用户输入的第一个额外参数,sys.argv[2]是第二个
        models = client.list_models() # 返回整包JSON响应格式见上面list_models函数中的注释
        for m in models.get("data", []):
            print(m.get("id"))
        return

    # 若第一个额外参数不是以--开头,则认为它是模型名称,覆盖默认配置中的模型
    if len(sys.argv) >= 2 and not sys.argv[1].startswith("--"):
        cfg.model = sys.argv[1]

    messages = [
        {"role": "system", "content": "你是一个严谨但不无聊的经济学专家"},
        {"role": "user", "content": "简洁的解释清楚A股和美股的差距在哪里?"},
    ]

    resp = client.chat(messages)

    # 兼容 OpenAI 风格返回：choices[0].message.content
    print(resp["choices"][0]["message"]["content"])

    # 如果你用的是 deepseek-reasoner，可能还会出现 reasoning_content
    msg = resp["choices"][0]["message"]
    if "reasoning_content" in msg:
        print("\n--- reasoning_content ---\n")
        print(msg["reasoning_content"])


# 脚本入口判断,当这个文件是直接运行的主程序时就执行main()函数,当作为模块被别的文件导入使用的时候就不执行main()函数 
if __name__ == "__main__":
    main()
