/**
 *本前端文件中5个函数send(),refreshModels(),checkAuth(),authSubmit,logoutBtn
 *对应的5个接口api/chat,api/models,api/login,api/register,api/logout中
 *仅send()和refreshModels()使用代码中单独封装的apiFetch函数发请求与后端接口通讯(权限型接口),其余三个函数均是直接使用原生fetch发请求(状态查询接口)
 *代码中多次用到的onclick关键字和addEventListener均处理点击事件
 *区别是onclick只能绑定一个事件处理函数,如果多次赋值会覆盖之前的;而addEventListener可以绑定多个事件处理函数,不会互相覆盖
 */
const el = (id) => document.getElementById(id); // const关键字代表常量引用,箭头函数是简写函数表达式;document.getElementById是浏览器提供的DOM API

/*
以下定义把HTML页面里的节点全部抓到JS变量里
El是element的缩写,表示该变量是一个DOM元素对象,通过id获取对应的元素对象
*/
const modelEl = el("model");
const systemEl = el("system");
const tempEl = el("temperature");
const topPEl = el("top_p");
const maxTokensEl = el("max_tokens");
const keepTurnsEl = el("keep_turns");
const showUsageEl = el("show_usage");
const showReasoningEl = el("show_reasoning");
const logoutBtn = el("logout");

const messagesEl = el("messages");
const inputEl = el("input");
const sendBtn = el("send");
const resetBtn = el("reset");
const statusEl = el("status");
const usageEl = el("usage");
const totalEl = el("total");
const refreshBtn = el("refreshModels");

const authOverlay = el("authOverlay");
const tabLogin = el("tabLogin");
const tabRegister = el("tabRegister");
const authEmail = el("authEmail");
const authPass = el("authPass");
const authSubmit = el("authSubmit");
const authErr = el("authErr"); // 错误提示区域


/**
 * 第二部分:认证模式与登录弹窗控制
 */
let authMode = "login"; // let代表变量名后面可以改

function showAuth(msg=""){ // js中的普通函数声明写法,msg是默认参数
  authOverlay.style.display = "flex"; // 让遮罩层authOverlay显示出来,并采用flex布局
  authErr.textContent = msg; // textContent表示元素的纯文本内容
  sendBtn.disabled = true;
}
function hideAuth(){
  authOverlay.style.display = "none";
  authErr.textContent = "";
  sendBtn.disabled = false;
}


/*重要封装!*/
async function apiFetch(url, opts={}){ // opts={}是第2个参数的默认值,可以不传，只有一个参数url
  // fetch是浏览器提供的HTTP请求API,第一个参数是URL,第二个参数是选项对象
  // credentials:"include"表示跨域请求时也要带上cookie
  // ...opts是展开传入的选项对象
  // 如果调用apiFetch时传了{method:"POST", headers:{...}}，就会和{credentials:"include"}合并成{credentials:"include", method:"POST", headers:{...}}
  const r = await fetch(url, { credentials:"include", ...opts });
  if (r.status === 401) { // ===在js中代表严格比较,不做乱七八糟的类型转换;==是宽松比较,会做隐式转换
    showAuth("请先登录/注册(防止他人消耗你的 tokens)");
    throw new Error("401");
  }
  return r;
}

// 匿名函数写法,此处的两个函数逻辑都是将函数直接交给onclick属性,而不是常见的"定义完以后将来再调用",类似于该事件的专属函数
// classList.add("active")是给元素添加一个类,remove("active")是删除一个类,通过切换类来控制选项卡的高亮显示;同时清空错误提示文本(.active类的UI样式定义见style.css)
tabLogin.onclick = () => { authMode="login"; tabLogin.classList.add("active"); tabRegister.classList.remove("active"); authErr.textContent=""; };
tabRegister.onclick = () => { authMode="register"; tabRegister.classList.add("active"); tabLogin.classList.remove("active"); authErr.textContent=""; };

/*登录/注册函数*/
authSubmit.onclick = async () => {
  const email = authEmail.value.trim();
  const password = authPass.value;
  if (!email || !password) { authErr.textContent="Email/Password 不能为空"; return; }

  const url = authMode === "login" ? "/api/login" : "/api/register"; // 三元运算符
  const r = await fetch(url, {
    method:"POST",
    credentials:"include",
    headers:{ "Content-Type":"application/json" }, // headers是HTTP请求头对象
    body: JSON.stringify({ email, password }) // 把请求体body中的JS对象转成JSON字符串
  });

  if (!r.ok) { authErr.textContent = "失败：" + await r.text(); return; } //await r.text()把响应体读成文本

  hideAuth();
  setStatus(authMode + " ok");
  refreshModels();
};

logoutBtn?.addEventListener("click", async () => { // ?.是可选链操作符,表示如果logoutBtn存在才调用addEventListener,否则不执行后面代码,避免报错
  try {
    const r = await fetch("/api/logout", {
      method: "POST",
      credentials: "include"
    });
    if (!r.ok) throw new Error("logout failed");

    resetChat();
    authEmail.value = "";
    authPass.value = "";
    showAuth("已退出，请登录或注册其他账号");
    setStatus("logged out");
  } catch (e) {
    setStatus("logout failed");
  }
});

async function checkAuth(){
  const r = await fetch("/api/me", { credentials:"include" });
  const data = await r.json();
  if (!data.logged_in) showAuth();
  else hideAuth();
}


let chatMessages = []; // 多轮对话记忆栈(前端保存即可),未写进数据库,只存在浏览器当前页面的JS里面(存数组)
let totalUsage = {}; // 累计token统计对象(存键值对)

function setStatus(s) { statusEl.textContent = s; } // 把状态栏文字改掉

/* 防XSS/HTML注入 */
function escapeHtml(s) {
  return (s ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;"); // ??代表空值合并运算符
}

/*往聊天区里新增一条消息气泡*/
function renderMsg(role, text) {
  const div = document.createElement("div"); // 动态创建一个新的<div>元素对象
  // 给该div设置两个类,反引号``是模板字符串,可以在其中嵌入表达式${},根据role的值来决定是"msg you"还是"msg ai"
  div.className = `msg ${role === "user" ? "you" : "ai"}`; // 三元运算符
  //innerHTML把字符串按HTML结构塞进去
  div.innerHTML = `
    <div class="meta">${role === "user" ? "You" : "AI"}</div>
    <div class="content">${escapeHtml(text)}</div>
  `;
  messagesEl.appendChild(div); // 把这个新div添加到messagesEl消息列表的末尾
  messagesEl.scrollTop = messagesEl.scrollHeight; // 滚动到底部
}

/*同步system输入框和chatMessages历史数组*/
function ensureSystem() {
  const sys = systemEl.value.trim();
  // 规则：如果 sys 有内容，就强制 chatMessages[0] 是 system；否则删除 system
  if (sys) {
    if (chatMessages.length && chatMessages[0].role === "system") {
      chatMessages[0].content = sys; // 更新已有system消息
    } else {
      chatMessages.unshift({ role: "system", content: sys }); //unshift头插
    }
  } else { // 若system输入框没有内容
    if (chatMessages.length && chatMessages[0].role === "system") { // 若chatMessages数组非空并且第一条消息是system
      chatMessages.shift(); // shift头删
    }
  }
}

/*累加函数*/
function updateUsage(usage) { // 类似Java中的void函数,不返回值,只修改状态;并且Js中函数不需要提前声明返回类型(这点和Java不同)
  if (!usage) return;
  // Object.entries把对象转成键值对数组,比如{a:1,b:2}变成[["a",1],["b",2]]
  // for(... of ...)是js的遍历语法,const [k,v]是解构赋值,把每个键值对数组解成k和v两个变量;比如["a",1]就会解成k="a",v=1
  // 总体来说这行代码遍历usage对象中的每一组键值对,每次循环时把键放进变量k,把值放进变量v
  for (const [k, v] of Object.entries(usage)) {
    // Number.isInteger(v)是JS提供的一个数字判断函数,判断一个数是否是整数;k是变量,故不能用totalUsage.k(访问的是字面属性名"k"),而是要用totalUsage[k]来访问对象属性
    if (Number.isInteger(v)) totalUsage[k] = (totalUsage[k] || 0) + v;
  }  
}

/*把一个usage对象,转换成一行适合在页面上显示的字符串(格式化函数)*/
function usageLine(obj) { // 明确返回字符串
  if (!obj) return "(no usage)";
  // map是数组方法,对数组里的每一项做一次转换,最后返回一个新的数组
  // `${k}=${v}``是模板字符串,把每个键值对转换成"k=v"的形式;比如{k:1}就会变成"k=1"
  // join()也是数组方法,把数组里的每一项用指定的分隔符连接成一个字符串;比如["a=1","b=2"].join("  ")就会变成"a=1  b=2"
  return Object.entries(obj).map(([k,v]) => `${k}=${v}`).join("  ");
}

 /*从后端拿到模型列表,然后刷新前端的模型下拉框*/
async function refreshModels() {
  try {
    const r = await apiFetch("/api/models"); // 调用上面封装好的apiFetch函数,向后端的"/api/models"接口发GET请求,拿到HTTP响应对象r
    const data = await r.json(); // 把响应体里的JSON内容读出来,并转成JS对象data
    const models = data.models || ["deepseek-chat", "deepseek-reasoner"];
    const cur = modelEl.value; // 在刷新下拉框之前,先记住当前用户选的是哪个模型

    modelEl.innerHTML = ""; // 清空旧下拉框
    for (const m of models) { // 遍历Models数组的每一个模型m
      const opt = document.createElement("option"); // 动态创建一个新的<option>元素对象
      opt.value = m; // 设置值
      opt.textContent = m; //设置显示给用户看的文字
      modelEl.appendChild(opt); // 将这个新创建的<option>挂到<select>元素modelEl下面,形成新的下拉选项
    }
    // 尽量恢复用户之前的选择,如果之前选的模型在新的模型列表里还存在,就把下拉框的值设置成之前选的那个模型
    if (cur && models.includes(cur)) modelEl.value = cur; // includes()是数组方法,判断是否包含某个元素,返回true/false

    // 更新状态栏
    setStatus(`models: ${models.length}`); // 此处又使用了模板字符串,等价于"models: " + models.length
  } catch (e) {
    setStatus("models refresh failed");
  }
}

/*前端聊天应用的主干逻辑,发送消息*/
async function send() {
  const text = inputEl.value.trim(); // trim()方法把字符串首尾空白字符去掉
  if (!text) return;

  inputEl.value = ""; // 清空输入框
  renderMsg("user", text); // 调用前面封装好的消息渲染函数renderMsg,把这条用户消息插入到聊天区(先渲染,再请求)

  ensureSystem(); // 调用前面封装好的ensureSystem()函数,保证system消息正确地存在于chatMessages的第一条(如果systemEl有内容的话)
  chatMessages.push({ role: "user", content: text }); // 将当前这轮用户输入加入"对话历史",push()方法在数组(chatMessages)末尾追加一个元素

  setStatus("thinking…");
  sendBtn.disabled = true;

  //构造请求体req,与后端的ChatRequest结构一致,一一对应
  const req = {
    messages: chatMessages,
    model: modelEl.value || "deepseek-chat",
    temperature: parseFloat(tempEl.value || "0.7"), // parseFloat()是JS提供的一个函数,把字符串解析成浮点数
    top_p: parseFloat(topPEl.value || "0.9"),
    max_tokens: parseInt(maxTokensEl.value || "1200", 10), // parseInt()是把字符串解析成整数,第二个参数10表示按十进制解析
    keep_turns: parseInt(keepTurnsEl.value || "20", 10),
  };

  try {
    const r = await apiFetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req) // 将JS对象req转成JSON字符串,作为请求体发送给后端
    });

    if (!r.ok) {
      const t = await r.text();
      throw new Error(`HTTP ${r.status}: ${t}`); // 抛出一个错误,然后直接跳转到后面的catch执行
    }

    const data = await r.json(); // 把后端响应解析成JS对象
    renderMsg("assistant", data.content || ""); // 将AI回复显示到页面上,如果data.content不存在就显示空字符串
    chatMessages.push({ role: "assistant", content: data.content || "" }); // 将AI的回复也追加进对话历史数组chatMessages

    if (showReasoningEl.checked && data.reasoning_content) {
      renderMsg("assistant", "[reasoning_content]\n" + data.reasoning_content);
    }

    if (showUsageEl.checked) {
      usageEl.textContent = "[usage] " + usageLine(data.usage);
      updateUsage(data.usage);
      totalEl.textContent = "[total] " + usageLine(totalUsage);
    } else {
      usageEl.textContent = "";
      totalEl.textContent = "";
    }

    setStatus("ok");
  } catch (e) {
    setStatus("error: " + e.message);
  } finally {
    sendBtn.disabled = false;
  }
}

/*刷新对话*/
function resetChat() {
  chatMessages = [];
  totalUsage = {};
  messagesEl.innerHTML = "";
  usageEl.textContent = "";
  totalEl.textContent = "";
  setStatus("reset ok");
  ensureSystem();
}

sendBtn.addEventListener("click", send);
resetBtn.addEventListener("click", resetChat);
refreshBtn.addEventListener("click", refreshModels);

/*Enter 发送，Shift+Enter 换行*/
// addEventListener给元素添加一个事件监听器,结构类似于  元素.addEventListener("事件类型",事件发生后执行的函数)
// 此处监听keydown键盘按下事件,(e) => {...}一个箭头函数,也是JS中的匿名函数写法,e是事件对象,是浏览器在事件发生之后自动传入的参数,包含了事件的各种信息;比如e.key就是按下的键是什么
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault(); // 阻止浏览器对此次事件执行默认行为(换行)
    send(); // 改成发送消息
  }
});

// 默认 system
systemEl.value = "你是一个严谨但不无聊的计算机导师。回答要结构清晰，必要时给例子。";
ensureSystem();
refreshModels();
setStatus("ready");
checkAuth();
