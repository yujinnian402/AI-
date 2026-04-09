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

const rootFaceRealtimeLoginBtn = el("rootFaceRealtimeLogin");
const rootFaceEnrollBtn = el("rootFaceEnroll");

const camModal = el("camModal");
const camTitle = el("camTitle");
const camVideo = el("camVideo");
const camOverlay = el("camOverlay");
const camCanvas = el("camCanvas");
const camCaptureEnrollBtn = el("camCaptureEnroll");
const camStopBtn = el("camStop");
const camHint = el("camHint");

const FACE_LOGIN_INTERVAL_MS = 1200;
const FACE_LOGIN_TIMEOUT_MS = 15000;
const FACE_REQUEST_TIMEOUT_MS = 7000;
const ENROLL_AUTO_CAPTURE_MS = 3000;
const FACE_PASS_CONSECUTIVE = 3;
const FACE_MIN_PASS_ELAPSED_MS = 2000;


/*下面定义的是一些前端的状态机*/
let authMode = "login"; // let代表变量名后面可以改
let camStream = null;
let faceLoopTimer = null;
let faceLoopBusy = false; //
let enrollAutoTimer = null; // 保存"自动录入倒计时"的定时器ID
let camMode = ""; // "login" | "enroll"


/**
 * 摄像头人脸识别模块的底层运行保障层
 */

/*异步等待指定毫秒数,提供异步暂停能力*/
function sleep(ms) { // 异步等待替代阻塞等待
  // JS是单线程+事件循环,Promise是JS提供的一个异步编程工具,它代表一个可能还没有结果的异步操作
  // 构造Promise时传入一个函数,该函数接受一个resolve参数,当异步操作完成时调用resolve()来通知外部Promise已经完成,并且可以继续执行后续代码
  return new Promise((resolve) => {
    // setTimeout注册一个定时器,当定时器到期后调用resolve函数
    // 从而让Promise进入完成状态,使得await sleep(ms)这一行的代码在等待指定毫秒数后继续往下执行 
    setTimeout(resolve, ms); 
  });
}

/** 分两种情况,正常返回和超时取消:
 * 正常返回: fetch()成功拿到响应,就直接返回这个响应对象,外部调用await fetchWithTimeout()的地方就会拿到这个响应对象继续往下执行
 * 超时取消: setTimeout()定时器到期后调用controller.abort(),这会给fetch()发出一个终止信号,使得fetch()抛出一个异常
 *    外部调用await fetchWithTimeout()的地方就会捕获到这个异常,进入catch块,可以在catch块里做一些超时后的处理逻辑(比如提示用户请求超时了) 
 */
async function fetchWithTimeout(url, options, timeoutMs = FACE_REQUEST_TIMEOUT_MS) { // url是请求地址,options是请求配置对象
  const controller = new AbortController(); // 创建一个中止控制器(浏览器提供的专门用于取消异步任务的对象)
  // 开一个setTimeout定时器,若到了timeoutMs就执行controller.abort(),abort()给绑定了这个signal的fetch发出终止请求信号
  const timer = setTimeout(() => controller.abort(), timeoutMs); 
  try {
    // 真正发请求的地方
    return await fetch(url, {
      ...options, // ...options代表对象展开
      // signal是控制器发信号的通道,abort()是给singal发一个终止信号
      signal: controller.signal, // 将controller控制器接到这个fetch请求上,使该请求监听signal,使得外部可以通过controller.abort()主动取消这次请求
    });
  } finally {
    clearTimeout(timer); // 取消setTimeout定时器
  }
}

/*异步等待视频准备就绪才开始拍照*/
async function waitVideoReady(video, timeoutMs = 5000) {
  const started = Date.now(); // 记录函数开始执行的时间戳,方便后续做超时判断
  // readyState是HTMLVideoElement的一个状态值,表示视频当前加载到什么程度
  while (video.readyState < 2) { // 0代表啥都没有,1是有一点元数据,2是已经有当前帧的数据,可以开始播放画面,更高数据更多
    if (Date.now() - started > timeoutMs) {
      throw new Error("摄像头画面初始化超时");
    }
    await sleep(80); // 控制异步轮询,检查一次还没超时就等80ms再检查下一次
  }
}

/**
 *摄像头弹窗UI+人脸框画布控制层 
 */


/*尝试将后端返回解析成结构化错误,若不行就当普通字符串显示(相对于原生的parse方法封装升级更好的处理异常情况)*/
function parseDetailFromText(raw) {
  try {
    const obj = JSON.parse(raw); // 尝试将字符串解析成JSON对象
    if (obj && obj.detail) return String(obj.detail); // 若obj存在且有detail字段就返回detail信息(强制转换为字符串)
  } catch (_) {} // 不关心异常内容
  return raw || "unknown error";
}

/*打开摄像头弹窗+初始化显示内容+清空画布*/
function showCamModal(title, hint = "") {
  camTitle.textContent = title; // 设置标题(纯文本,不会解析HTML,防XSS)
  camHint.textContent = hint; //设置提示文本
  camModal.style.display = "flex"; // 将弹窗从隐藏变成显示
  clearFaceOverlay(); // 打开摄像头时,先把旧的框清掉
}

/*关闭摄像头弹窗+清理提示*/
function hideCamModal() {
  camModal.style.display = "none";
  camHint.textContent = ""; // 清除掉提示文字
}

/*让canvas画布尺寸 = 视频实际分辨率*/
function syncOverlaySize() {
  if (!camOverlay || !camVideo) return; // 防御性编程
  // 视频真实像素分辨率
  const w = camVideo.videoWidth;
  const h = camVideo.videoHeight;
  if (!w || !h) return; // 若视频还没加载,直接退出
  if (camOverlay.width !== w) camOverlay.width = w;
  if (camOverlay.height !== h) camOverlay.height = h;
}

/*清空canvas上的所有内容(人脸框)*/
function clearFaceOverlay() {
  if (!camOverlay) return;
  const ctx = camOverlay.getContext("2d"); // 获取canvas的画笔对象
  if (!ctx) return;
  syncOverlaySize(); // 同步尺寸
  ctx.clearRect(0, 0, camOverlay.width, camOverlay.height); // 清空整个画布
}

/**
 *识别结果渲染层 
 */

/*把后端返回的人脸识别结果,画成前端摄像头画面上的框和提示文字*/
function drawFaceOverlay(bbox, score, threshold, matched) {
  /*画之前先清空画布*/
  if (!camOverlay) return;
  const ctx = camOverlay.getContext("2d"); // 从canvas拿到一个2D绘图上下文对象,通过它可以在canvas上画图
  if (!ctx) return;
  syncOverlaySize(); // 先将overlay画布尺寸同步为和视频一致,确保画的框能对上人脸位置
  const w = camOverlay.width;
  const h = camOverlay.height;
  ctx.clearRect(0, 0, w, h);
  if (!bbox) return;

  /*画人脸框*/
  const x1 = Math.max(0, Math.min(w - 1, Number(bbox.x1 || 0))); // 坐标钳制,保证坐标在合法范围内
  const y1 = Math.max(0, Math.min(h - 1, Number(bbox.y1 || 0)));
  const x2 = Math.max(0, Math.min(w - 1, Number(bbox.x2 || 0)));
  const y2 = Math.max(0, Math.min(h - 1, Number(bbox.y2 || 0)));
  // 算出框的宽高
  const bw = Math.max(1, x2 - x1);
  const bh = Math.max(1, y2 - y1);

  ctx.lineWidth = 3; // 设置边框线宽为3像素
  ctx.strokeStyle = matched ? "#22c55e" : "#f59e0b"; // 用到了三元运算符,根据matched决定框的颜色,命中就是绿色,未命中就是橙色
  ctx.strokeRect(x1, y1, bw, bh); // 真正画边框,参数是框的左上角坐标(x1,y1)和宽高(bw,bh)

  /*画文字*/
  // 拼出要显示的文字,Number确保是数字,.toFixed()方法保证n位小数
  const text = "score=" + Number(score || 0).toFixed(4) + " / th=" + Number(threshold || 0).toFixed(2);
  ctx.font = "16px sans-serif"; // 设置字体,后续测量文字宽度和绘制文字都会用这个字体
  const tw = ctx.measureText(text).width + 12; // 得出之后的文字背景框的宽度,比文字宽12像素,留点内边距
  // 确定文字背景框的左上部分坐标tx,ty;让它尽量贴近人脸框的左上角(x1,y1),但又不能超出画布边界
  const tx = x1;
  const ty = Math.max(0, y1 - 28);
  ctx.fillStyle = "rgba(0,0,0,0.7)"; // 设置填充颜色为半透明黑色,作为文字背景
  ctx.fillRect(tx, ty, tw, 24); // 画一个矩形背景条
  ctx.fillStyle = "#ffffff"; // 把接下来文字填充颜色改为白色
  ctx.fillText(text, tx + 6, ty + 17); // 把文字画到背景框里
}

/*真正打开摄像头并将摄像头视频流接到页面video元素上*/
async function startCamera() {
  if (camStream) return;
  camStream = await navigator.mediaDevices.getUserMedia({ // na...Media是浏览器提供的媒体设备采集接口
    video: { facingMode: "user" },
    audio: false
  });
  camVideo.srcObject = camStream; // 把拿到的媒体流绑定给video元素,视频就会显示摄像头画面
  await camVideo.play(); // 让视频开始播放
  await waitVideoReady(camVideo, 5000); // 等视频真正进入有帧数据可用的状态,最长等待5秒
  syncOverlaySize(); // 摄像头准备好之后将overlay画布尺寸同步为视频尺寸
}

/*负责把摄像头相关的一切运行状态和资源,全部停干净(回收了定时器,延时器,摄像头轨道,UI/状态)*/
function stopCamera() {
  // 如果当前周期性识别循环定时器,就停掉
  if (faceLoopTimer) {
    clearInterval(faceLoopTimer);
    faceLoopTimer = null; // 表示状态重置
  }
  // 停掉自动录入倒计时
  if (enrollAutoTimer) {
    clearTimeout(enrollAutoTimer);
    enrollAutoTimer = null;
  }
  // 关闭摄像头硬件流
  if (camStream) {
    for (const t of camStream.getTracks()) t.stop(); // 从媒体流里取出所有轨道(比如音频轨道,视频轨道等),逐个调用stop()方法停掉,彻底关闭摄像头
    camStream = null;
  }
  camVideo.srcObject = null; // 解除video绑定
  clearFaceOverlay(); // 清空画布
  faceLoopBusy = false; // 告诉系统:当前没有识别任务在忙
  camMode = ""; // 告诉系统:摄像头模块已经退出当前模式,不再是login也不再是enroll
}

/*从当前video里的摄像头画面抓一帧,并转成base64图片字符串发给后端(截图函数)*/
function captureFrameBase64() {
  // 拿到当前视频真实分辨率
  const w = camVideo.videoWidth;
  const h = camVideo.videoHeight;
  if (!w || !h) {
    throw new Error("摄像头画面尚未准备好");
  }
  // 把用于截图的canvas尺寸设置为和视频一致
  camCanvas.width = w;
  camCanvas.height = h;
  const ctx = camCanvas.getContext("2d");
  ctx.drawImage(camVideo, 0, 0, w, h); // 把当前video里的这一帧,画到canvas上(前端抓帧经典方法)
  return camCanvas.toDataURL("image/jpeg", 0.9); // 把canvas当前内容导出成base64编码的Data URL字符串,参数是图片格式JPEG和质量(0.9代表90%质量的jpg)
}

/*前端核心业务函数*/
async function runRealtimeRootFaceLogin(email) {
  const startedAt = Date.now(); // 记录函数开始时间,Date.now()返回当前时间戳(毫秒),方便后续做超时判断以及控制
  let attempts = 0; // 记录已经做了多少次preview尝试
  let passStreak = 0; // 记录连续命中次数

  while (camMode === "login" && camStream && Date.now() - startedAt < FACE_LOGIN_TIMEOUT_MS) {
    // 如果发现正在忙，等待80ms然后进入下一轮再检测，如果还是正在忙，继续等80ms然后再进入下一轮，如此循环
    // 直到某一次一轮开始进来检测发现不是正在忙，就不执行if块，直接执行下面的标价正在忙，然后本轮开始真正执行后面的业务代码
    if (faceLoopBusy) {
      await sleep(80);
      continue; // 直接跳过当前这一轮，进入下一轮从头开始
    }
    faceLoopBusy = true;

    try {
      const elapsed = Date.now() - startedAt; // 计算从函数开始到当前这一轮已经过去多久
      const imageB64 = captureFrameBase64(); // 抓取当前摄像头的一帧并编码成base64图片字符串 
      
      // 给preview接口发送名为preview的请求
      const preview = await fetchWithTimeout(
        "/api/root/face/preview",
        {
          method: "POST",
          credentials: "include", // 表示请求要带上cookie/session
          headers: { "Content-Type": "application/json" }, // 告诉后端请求体是Json
          body: JSON.stringify({ email: email, image_b64: imageB64 }), // 把JS对象转成JSON字符串发出去
        },
        FACE_REQUEST_TIMEOUT_MS,
      );

      attempts += 1;

      // preview请求失败分支
      if (!preview.ok) {
        const raw = await preview.text(); // 将错误响应体作为纯文本读出来
        const detail = parseDetailFromText(raw); // 调用前面写的解析函数尝试把错误信息解析成结构化的detail字段,如果解析失败就直接用原文本

        // 错误码403或400直接终止
        if (preview.status === 403) {
          stopCamera();
          hideCamModal();
          authErr.textContent = "root 邮箱不匹配或权限不足";
          setStatus("root face forbidden");
          return false;
        }
        if (preview.status === 400 && detail.indexOf("Root face not enrolled") >= 0) { // indexOf是字符串的查找子串位置方法,只要子串第一次出现的位置大于0就算匹配成功
          stopCamera(); // 先停止摄像头系统本身的运行(系统层动作:将这些"后台运行状态"全部收干净)(处理系统内部)
          hideCamModal(); // 再讲摄像头弹窗这个界面隐藏掉(纯UI层动作)(处理用户界面)
          authErr.textContent = "尚未录入人脸模板,请先登录后录入";
          setStatus("root face not enrolled");
          return false;
        }
         // 其他错误错误则不终止,继续下一轮
        passStreak = 0;
        clearFaceOverlay();
        camHint.textContent =
          "识别中(" + attempts + "),已用时 " + Math.floor(elapsed / 1000) + "s,结果: " + detail; // 更新摄像头提示区
        await sleep(FACE_LOGIN_INTERVAL_MS); // 休息一个固定间隔再开始下一轮
        continue;
      }
      // preview请求成功分支
      const p = await preview.json(); // 成功响应按照JSON解析，收到了后端root_face_preview接口return的JSON数据
      drawFaceOverlay(p.bbox, p.score, p.threshold, p.matched); // 把后端返回的JSON数据结果调用前面封装好的函数实时画到视频上
      
      // 连续命中计数逻辑
      if (p.matched && elapsed >= FACE_MIN_PASS_ELAPSED_MS) {
        passStreak += 1;
      } else {
        passStreak = 0; // 只要有一轮不满足就直接清零
      }
      
      // 前端体验层亮点，更新实时提示
      camHint.textContent =
        "相似度 " + Number(p.score).toFixed(4) +
        " / 阈值 " + Number(p.threshold).toFixed(2) +
        ",连续命中 " + passStreak + "/" + FACE_PASS_CONSECUTIVE;
      
      // 达到连续命中阈值之后,开始challenge+最终login
      if (passStreak >= FACE_PASS_CONSECUTIVE) {
        // 先找challenge接口拿challenge nonce,发出名为c的请求
        const c = await fetchWithTimeout(
          "/api/root/face/challenge",
          { credentials: "include" },
          4000,
        );
        // c请求失败分支
        if (!c.ok) {
          stopCamera();
          hideCamModal();
          authErr.textContent = "challenge 获取失败";
          setStatus("face challenge failed");
          return false;
        }
        // c请求成功分支
        // 从后端响应体里取出并解析nonce
        const cData = await c.json();
        const nonce = cData.nonce || "";

        // 发最终登录请求r
        const r = await fetchWithTimeout(
          "/api/root/face/login",
          {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email: email, nonce: nonce, image_b64: imageB64 }),
          },
          FACE_REQUEST_TIMEOUT_MS,
        );
        // 最终登录成功分支
        if (r.ok) {
          stopCamera();
          hideCamModal();
          hideAuth();
          authErr.textContent = "";
          setStatus("root 实时人脸登录成功");
          await refreshModels(); // 登录成功后刷新模型列表
          return true;
        }
        // 最终登录失败分支
        const lr = await r.text();
        const ldetail = parseDetailFromText(lr);
        passStreak = 0; // 最终登录层级的校验失败后,把连续命中清零(即使前面preview层级的校验连续命中达到阈值顺利通过)
        camHint.textContent = "最终校验未通过: " + ldetail;
      }
    // 捕获整个try块内任意异常,汇总统一显示到摄像头提示区
    } catch (e) {
      camHint.textContent = "识别请求异常: " + e.message;
    } finally {
      faceLoopBusy = false; // 不论成功失败与否,每一轮最后结束之后都释放忙碌锁,让下一轮可以继续进行识别尝试
    }

    await sleep(FACE_LOGIN_INTERVAL_MS); // 每一轮结束后的节流等待
  }

  // 超时分支,无论是因为时间到了还是用户手动停掉摄像头,只要还处于登录模式,都给出超时提示
  if (camMode === "login") { // 在JS中=是赋值,==是宽松比较(会偷偷做类型转换),===是严格比较(要求必须值相等同时类型相等)
    stopCamera();
    hideCamModal();
    authErr.textContent = "人脸登录超时,请调整光线/角度后重试";
    setStatus("root face login timeout");
  }
  return false;
}

async function enrollRootFaceFromCurrentFrame() {
  try {
    const me = await fetchWithTimeout("/api/me", { credentials: "include" }, 4000);
    const meData = await me.json();
    if (!meData.logged_in || meData.role !== "root") {
      camHint.textContent = "只有已登录 root 才能录入";
      return false;
    }

    const imageB64 = captureFrameBase64();
    const r = await fetchWithTimeout(
      "/api/root/face/enroll",
      {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image_b64: imageB64 }),
      },
      FACE_REQUEST_TIMEOUT_MS,
    );

    if (!r.ok) {
      const raw = await r.text();
      camHint.textContent = "录入失败: " + parseDetailFromText(raw);
      return false;
    }

    camHint.textContent = "录入成功,摄像头即将关闭";
    setStatus("root face enrolled");

    setTimeout(() => {
      stopCamera();
      hideCamModal();
    }, 900);

    return true;
  } catch (e) {
    camHint.textContent = "录入请求异常: " + e.message;
    return false;
  }
}

rootFaceRealtimeLoginBtn?.addEventListener("click", async () => {
  const email = authEmail.value.trim();
  if (!email) {
    authErr.textContent = "请先输入 root 邮箱";
    return;
  }

  try {
    camMode = "login";
    showCamModal("Root 实时人脸登录", "请保持单人脸、正对镜头；将显示实时相似度与框选,连续命中后通过");
    camCaptureEnrollBtn.style.display = "none";
    await startCamera();
    const ok = await runRealtimeRootFaceLogin(email);
    if (!ok) {
      // 已在 runRealtimeRootFaceLogin 内处理失败（UI/状态）,这里的if是在进行调用层预留处理权
    }
  } catch (e) {
    stopCamera();
    hideCamModal();
    authErr.textContent = "无法打开摄像头: " + e.message;
  }
});

rootFaceEnrollBtn?.addEventListener("click", async () => {
  try {
    const me = await fetchWithTimeout("/api/me", { credentials: "include" }, 4000);
    const meData = await me.json();
    if (!meData.logged_in || meData.role !== "root") {
      setStatus("请先用 root 账号登录再录入");
      showAuth("请先用 root 账号登录再录入人脸");
      return;
    }

    camMode = "enroll";
    showCamModal("Root 人脸模板录入", "请正对镜头,3 秒后自动录入,也可手动点击拍照录入");
    camCaptureEnrollBtn.style.display = "inline-block";
    await startCamera();

    if (enrollAutoTimer) {
      clearTimeout(enrollAutoTimer);
    }
    enrollAutoTimer = setTimeout(async () => {
      if (camMode === "enroll" && camStream) {
        await enrollRootFaceFromCurrentFrame();
      }
    }, ENROLL_AUTO_CAPTURE_MS);
  } catch (e) {
    stopCamera();
    hideCamModal();
    setStatus("摄像头打开失败: " + e.message);
  }
});

camCaptureEnrollBtn?.addEventListener("click", async () => {
  await enrollRootFaceFromCurrentFrame();
});

camStopBtn?.addEventListener("click", () => {
  stopCamera();
  hideCamModal();
});

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
async function apiFetch(url, opts={}){ // opts={}是第2个参数的默认值,可以不传,只有一个参数url
  // fetch是浏览器提供的HTTP请求API,第一个参数是URL,第二个参数是选项对象
  // credentials:"include"表示跨域请求时也要带上cookie
  // ...opts是展开传入的选项对象
  // 如果调用apiFetch时传了{method:"POST", headers:{...}},就会和{credentials:"include"}合并成{credentials:"include", method:"POST", headers:{...}}
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
    showAuth("已退出,请登录或注册其他账号");
    setStatus("logged out");
  } catch (e) {
    setStatus("logout failed");
  }
});

async function checkAuth(){
  const r = await fetch("/api/me", { credentials:"include" });
  const data = await r.json();
  if (!data.logged_in){ 
    showAuth();
    return;
  } 
  hideAuth();
  if (data.role) setStatus("logged in as " + data.role);
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
  // 规则：如果 sys 有内容,就强制 chatMessages[0] 是 system；否则删除 system
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

/*Enter 发送,Shift+Enter 换行*/
// addEventListener给元素添加一个事件监听器,结构类似于  元素.addEventListener("事件类型",事件发生后执行的函数)
// 此处监听keydown键盘按下事件,(e) => {...}一个箭头函数,也是JS中的匿名函数写法,e是事件对象,是浏览器在事件发生之后自动传入的参数,包含了事件的各种信息;比如e.key就是按下的键是什么
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault(); // 阻止浏览器对此次事件执行默认行为(换行)
    send(); // 改成发送消息
  }
});

// 默认 system
systemEl.value = "你是一个严谨但不无聊的计算机导师。回答要结构清晰,必要时给例子。";
ensureSystem();
refreshModels();
setStatus("ready");
checkAuth();

/*给浏览器窗口注册一个事件监听器*/
// window是浏览器最顶层对象,beforeunload是一个浏览器生命周期事件(同步阶段,不能处理异步操作)
// 在用户即将离开页面(刷新/关闭/跳转)之前触发;监听这个事件的函数里可以执行一些清理工作,比如停掉摄像头,回收资源等
window.addEventListener("beforeunload", () => {
  // 此处不多调用hideCamModal()了,因为页面都要走了,不需要再管UI了;但停掉摄像头是必须的,不然摄像头可能会一直开着,造成资源浪费甚至隐私泄露
  stopCamera();
});
