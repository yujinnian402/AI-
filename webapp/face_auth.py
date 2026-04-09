import base64
import cv2
import numpy as np
from typing import Dict, List
from insightface.app import FaceAnalysis


class FaceAuthEngine:
    def __init__(self):
        self.app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"]) # 创建一个FaceAnalysis实例self.app
        self.app.prepare(ctx_id=-1, det_size=(640, 640))

    def _decode_b64_image(self, image_b64: str) -> np.ndarray: # no.ndarray是Numpy数组的多维数组,高性能+连续内存
        """
        Python中_开头函数代表内部辅助私有方法
        将字符串图片转成图像矩阵
        """
        # 支持 data:image/jpeg;base64,xxxx 或纯 base64
        if "," in image_b64:
            image_b64 = image_b64.split(",", 1)[1] # split()是字符串方法,按照,分隔符切开字符串,最多只切一次,返回一个列表,取第二部分就是纯base64了
        raw = base64.b64decode(image_b64) # 将base64编码的字符串解码回原始二进制字节,解码后得到一驼图片文件的原始二进制内容
        # 将图片字节流raw包装成一个一维Numpy数组,每个元素代表一个字节
        arr = np.frombuffer(raw, dtype=np.uint8) # np.frombuffer()方法从一块原始内存缓冲区中构造一个numpy数组视图,dtype=np.uint8表示数组元素类型设定为8位无符号整数
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR) # cv2.imdecode()方法将内存里的压缩图片数据,解码成opencv图像矩阵,cv2.IMREAD_COLOR表示以彩色图像方式解码
        if img is None:
            raise ValueError("Invalid image")
        return img

    def _resize_max_side(self, img: np.ndarray, max_side: int = 1280) -> np.ndarray:
        """限制图像尺寸"""
        h, w = img.shape[:2] # .shape是numpy数组的属性,返回一个元组表示数组的维度大小,[:2]表示切片,取前两个元素,也就是图像的高度和宽度
        m = max(h, w)
        if m <= max_side:
            return img
        scale = max_side / float(m)
        # 按比例算新高,新宽,至少有一边等于 max_side
        nw = max(1, int(w * scale))
        nh = max(1, int(h * scale))
        return cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA) # INTER_AREA是opencb中比较适合缩小如图片的一种插值方法

    def _enhance_low_light(self, img: np.ndarray) -> np.ndarray:
        """弱光增强"""
        # cv2.cvtColor是opencv中最常用的函数之一,用于颜色空间转换,cv2.cvtColor(src, code),src是输入图像,code是转换规则(e.g:cv2.COLOR_BGR2GRAY)
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB) # 将图像从opencv默认的BGR颜色空间转成LAB,l是亮度,a是绿色到红色,b是蓝色到黄色
        l, a, b = cv2.split(lab) # 将三个通道拆开
        # CLAHE是对比度限制自适应直方图均衡化,用于局部提亮+局部增强比对度
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)) # cliplimit限制增强强度,tileGridSize将图像划分成很多小块分别处理
        l2 = clahe.apply(l) # 只对亮度通道做增强
        merged = cv2.merge((l2, a, b)) # 将增强后的亮度通道和原来的a,b通道合并回LAB图像
        return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR) # 再转回opencv常用的BGR颜色空间

    def _pick_primary_face(self, faces):
        """多张脸时选主脸"""
        if len(faces) == 1:
            return faces[0]
        if len(faces) == 0:
            return None

        with_area = [] # 带面积信息的人脸列表,每一个元素是一个二元组(area, f)
        for f in faces:
            x1, y1, x2, y2 = f.bbox # 解包赋值,bbox是人脸框的坐标(x1,y1)是左上角,(x2,y2)是右下角
            area = max(0.0, float(x2 - x1)) * max(0.0, float(y2 - y1)) # 防御性编程,算脸部面积
            with_area.append((area, f)) # append是列表方法,往列表末尾追加元素
        # sort()是列表的原地排序方法,key参数指定排序依据,这里是按照面积从大到小排序,lambda是匿名函数写法,reverse代表倒序排序(大到小)
        with_area.sort(key=lambda x: x[0], reverse=True)
        if len(with_area) >= 2 and with_area[1][0] > 0 and with_area[0][0] / with_area[1][0] < 1.8: # with_area[1][0]是第二大的脸的面积
            raise ValueError("Multiple faces detected; keep only one face in camera")
        return with_area[0][1] # 返回第一大的脸的脸部信息对象

    def _extract_with_fallback(self, img: np.ndarray):
        """多策略提取人脸"""
        orig_w = img.shape[1]
        candidates = [] # 每个元素的结构是(img, scale),scale是这个尺寸相对于原图的缩放比例
        base = self._resize_max_side(img, 1280)
        base_scale = base.shape[1] / float(orig_w)
        candidates.append((base, base_scale))
        candidates.append((self._enhance_low_light(base), base_scale))

        if base.shape[0] > 720 or base.shape[1] > 720:
            small = self._resize_max_side(base, 720)
            small_scale = small.shape[1] / float(orig_w)
            candidates.append((small, small_scale))
            candidates.append((self._enhance_low_light(small), small_scale))

        last_multi_face_err = None # 定义最后一次多脸错误的表示变量
        for cand, scale in candidates: # Python的解包遍历写法(遍历+拆元组)
            # 调用前面__init__中创建的FaceAnalysis实例的get方法,输入np.ndarray图像矩阵,输出一个人脸信息列表,每个元素是一个人脸信息对象,包含bbox和embedding等属性
            # 一张图中可能有多个人脸,所以返回的是一个列表,人脸列表
            faces = self.app.get(cand)
            if len(faces) == 0:
                continue # 跳过当前轮次,直接进入下一轮for循环
            # 如果至少有一张脸,就尝试选主脸
            try:
                return self._pick_primary_face(faces), scale # 此处return结束整个函数
            except ValueError as e:
                last_multi_face_err = e

        if last_multi_face_err:
            raise last_multi_face_err
        raise ValueError("No face detected; move closer, face camera directly, and improve lighting")

    def extract_face_embedding_and_bbox(self, image_b64: str) -> Dict[str, object]: # 该类对外提供的核心方法之一
        """提取特征embedding和框坐标bbox"""
        img = self._decode_b64_image(image_b64)
        h, w = img.shape[:2]
        face, scale = self._extract_with_fallback(img)

        if not scale:
            scale = 1.0
        x1, y1, x2, y2 = [float(v) for v in face.bbox] # 列表推导式+解包赋值
        bx1 = max(0, min(w - 1, int(round(x1 / scale)))) # 把候选图里的x1还原成原图坐标,取整,然后限制在[0, w-1]的合法范围内，防御性编程
        by1 = max(0, min(h - 1, int(round(y1 / scale))))
        bx2 = max(0, min(w - 1, int(round(x2 / scale))))
        by2 = max(0, min(h - 1, int(round(y2 / scale))))

        # face.normed_embedding表示从人脸对象中提取出归一化的人脸特征向量,它是一个numpy数组
        # 调用astype(np.float32)将其转换成32位浮点数类型,再调用tolist()方法将其转换成Python的列表形式,方便后续json序列化等操作
        emb = face.normed_embedding.astype(np.float32).tolist() 
        return {
            "embedding": emb,
            "bbox": {
                "x1": bx1,
                "y1": by1,
                "x2": bx2,
                "y2": by2,
            },
        }

    def extract_normed_embedding(self, image_b64: str) -> List[float]:
        """只提取特征向量embedding"""
        info = self.extract_face_embedding_and_bbox(image_b64)
        return info["embedding"]

    @staticmethod # decorator装饰器,表示下面这个方法是一个静态方法,不需要访问类的属性和实例的属性,可以直接通过类名调用(该函数只输入两个参数a,b)
    def cosine_similarity(a: List[float], b: List[float]) -> float:
        """余弦相似度计算方法"""
        # 将输入向量a转换成一个float32类型的numpy数组
        va = np.asarray(a, dtype=np.float32) # np.asarray()方法将输入的数据转换成numpy数组ndarray(方便后面要进行的向量运算)
        vb = np.asarray(b, dtype=np.float32)
        denom = (np.linalg.norm(va) * np.linalg.norm(vb)) + 1e-8 # 分别求两个向量的长度再想乘,作为余弦相似度的分母,加上一个很小的数防止除零错误
        return float(np.dot(va, vb) / denom) # np.dot()方法计算点积,float将计算出来的结果numpy.float32/float64类型转换成Python原生float类型


face_engine = FaceAuthEngine()