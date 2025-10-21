import base64
import hashlib
import struct
from typing import Dict, Union

# pycryptodome库用于DES加解密
from Crypto.Cipher import DES
from Crypto.Util.Padding import pad, unpad


class NativeUtils:
    """
    对 com.sogou.upd.x1.utils.NativeUtils 的原生函数进行Python复现。
    所有方法均为静态方法，以匹配JNI的实现方式。
    """
    # 这个魔术字符串用于密钥派生
    _MAGIC_XOR_STRING = b"K01ABab98DES part of OpenSSL 1.0.0a 1 Jun 2010"

    # 从反编译代码中提取的硬编码种子数据，用于DES密钥生成
    # 原始代码中的值是32位整数，这里我们使用 struct 将它们打包成小端字节序
    _DES_SEEDS = {
        1: struct.pack('<II', 0x61572706, 0xb7a1112),
        2: struct.pack('<II', 0xd5871247, 0x1e1fe526),
        3: struct.pack('<II', 0x4e702a3, 0x5b1a05f6),
        4: struct.pack('<II', 0xe4620226, 0xee0f05d7),
        5: struct.pack('<II', 0x4c22753, 0xe5a6102),
    }

    # 用于MD5签名的种子数据
    _MD5_SEEDS = {
        1: struct.pack('<IIIIIIII',
                       0x61572706, 0xb7a1112, 0x4172276, 0xbb0f2422,
                       0x21d242a3, 0x7e7f4107, 0x24073233, 0x6bba7432),
        2: struct.pack('<IIIIIIII',
                       0x4c22753, 0xe5a6102, 0x54775226, 0x7e7a0122,
                       0x54276726, 0x1e1a41e2, 0x41270773, 0x4b1a3452),
    }

    @staticmethod
    def _derive_key(seed: bytes, length: int) -> bytes:
        """
        根据种子派生密钥的核心逻辑。
        1. 与魔术字符串进行异或(XOR)。
        2. 对每个字节进行高低4位翻转 (Nibble Swap)。
        """
        # 异或操作
        # C代码从魔术字符串的第二个字节('0')开始取
        xor_key = NativeUtils._MAGIC_XOR_STRING[1: 1 + length]
        xored = bytes([b ^ k for b, k in zip(seed, xor_key)])

        # 高低4位翻转
        swapped = bytes([(b >> 4) | ((b & 0x0F) << 4) for b in xored])
        return swapped

    @staticmethod
    def _get_des_key(key_type: int) -> bytes:
        """根据类型获取8字节的DES密钥"""
        if key_type not in NativeUtils._DES_SEEDS:
            raise ValueError(f"Invalid DES key_type: {key_type}")
        seed = NativeUtils._DES_SEEDS[key_type]
        return NativeUtils._derive_key(seed, 8)

    @staticmethod
    def _get_md5_key(key_type: int) -> bytes:
        """根据类型获取32字节的MD5密钥"""
        if key_type not in NativeUtils._MD5_SEEDS:
            raise ValueError(f"Invalid MD5 key_type: {key_type}")
        seed = NativeUtils._MD5_SEEDS[key_type]
        # 在MD5的派生逻辑中，XOR key是循环使用的
        long_xor_key = (NativeUtils._MAGIC_XOR_STRING[1:9] * (32 // 8 + 1))[:32]
        xored = bytes([b ^ k for b, k in zip(seed, long_xor_key)])
        swapped = bytes([(b >> 4) | ((b & 0x0F) << 4) for b in xored])
        return swapped

    @staticmethod
    def encrypt(plain_text: str, key_type: int) -> bytes:
        """
        Java_com_sogou_upd_x1_utils_NativeUtils_a 的实现。
        功能：DES加密
        :param plain_text: 待加密的明文字符串
        :param key_type: 密钥类型 (1-5)
        :return: 加密后的字节流
        """
        key = NativeUtils._get_des_key(key_type)
        cipher = DES.new(key, DES.MODE_ECB)
        # 对数据进行编码和填充
        padded_data = pad(plain_text.encode('utf-8'), DES.block_size)
        encrypted = cipher.encrypt(padded_data)
        return encrypted

    @staticmethod
    def decrypt(cipher_text: bytes, key_type: int) -> str:
        """
        Java_com_sogou_upd_x1_utils_NativeUtils_b 的实现。
        功能：DES解密
        :param cipher_text: 待解密的字节流
        :param key_type: 密钥类型 (1-5)
        :return: 解密后的明文字符串
        """
        key = NativeUtils._get_des_key(key_type)
        cipher = DES.new(key, DES.MODE_ECB)
        decrypted_padded = cipher.decrypt(cipher_text)
        # 去除填充并解码
        unpadded = unpad(decrypted_padded, DES.block_size)
        return unpadded.decode('utf-8')

    @staticmethod
    def encrypt_to_base64(plain_text: str, key_type: int) -> str:
        """
        Java_com_sogou_upd_x1_utils_NativeUtils_c 的实现。
        功能：DES加密后进行Base64编码
        :param plain_text: 待加密的明文字符串
        :param key_type: 密钥类型 (1-5)
        :return: Base64编码后的加密字符串
        """
        encrypted_bytes = NativeUtils.encrypt(plain_text, key_type)
        return base64.b64encode(encrypted_bytes).decode('ascii')

    @staticmethod
    def decrypt_base64(base64_text: str, key_type: int) -> str:
        """
        Java_com_sogou_upd_x1_utils_NativeUtils_d 的实现 (根据对称性推断)。
        功能：Base64解码后进行DES解密
        :param base64_text: Base64编码的加密字符串
        :param key_type: 密钥类型 (1-5)
        :return: 解密后的明文字符串
        """
        decoded_bytes = base64.b64decode(base64_text)
        return NativeUtils.decrypt(decoded_bytes, key_type)

    @staticmethod
    def sign_MD5(text_to_sign: str, key_type: int) -> str:
        """
        Java_com_sogou_upd_x1_utils_NativeUtils_f 和 h 的实现。
        功能：MD5签名
        :param text_to_sign: 待签名的字符串
        :param key_type: 密钥类型 (1-2)
        :return: 32位小写的MD5签名值
        """
        md5_key = NativeUtils._get_md5_key(key_type)
        data_to_hash = text_to_sign.encode('utf-8') + md5_key

        md5 = hashlib.md5()
        md5.update(data_to_hash)
        return md5.hexdigest()

    # h方法在逻辑上与f方法相同
    h = sign_MD5

    @staticmethod
    def sign_dict_MD5(params: Dict[str, Union[str, int]], extra_str: str, key_type: int) -> str:
        """
        Java_com_sogou_upd_x1_utils_NativeUtils_e 的实现。
        功能：对参数字典进行排序、拼接、签名
        :param params: 参数字典
        :param extra_str: 附加在参数串后的字符串
        :param key_type: 密钥类型 (1-2)
        :return: 32位小写的MD5签名值
        """
        # 1. 按key的字母顺序排序
        sorted_keys = sorted(params.keys())

        # 2. 拼接成 key1=value1&key2=value2 的形式
        query_parts = [f"{k}={params[k]}" for k in sorted_keys]
        query_string = "&".join(query_parts)

        # 3. 拼接附加字符串
        string_to_sign = query_string + extra_str

        # 4. 调用f方法进行签名
        return NativeUtils.sign_MD5(string_to_sign, key_type)

    @staticmethod
    def get_key() -> str:
        """
        Java_com_sogou_upd_x1_utils_NativeUtils_g 的实现。
        功能：获取一个固定的密钥字符串
        :return: key_type=4派生出的DES密钥的字符串形式
        """
        # 这个函数的逻辑是生成key_type=4的密钥并返回
        # 原始代码中有一个小错误，它只异或了7个字节
        # 我们这里精确复现
        seed = struct.pack('<II', 0xe4620216, 0xee0f05d7)  # 注意原始值是0xe4620216
        xor_key = NativeUtils._MAGIC_XOR_STRING[1: 1 + 8]

        # 精确复现C代码中的循环 (iVar3从1到7)
        key_bytes_list = list(seed)
        for i in range(1, 8):
            key_bytes_list[i] ^= xor_key[i]

        xored = bytes(key_bytes_list)

        swapped = bytes([(b >> 4) | ((b & 0x0F) << 4) for b in xored])

        # C代码最后将其作为C字符串返回
        return swapped.decode('latin-1')


# --- 示例用法 ---
if __name__ == "__main__":
    test_data = b'0\x81\xd4\x14\xfb\x18\x0c\xdc\xef\xe2\x19\xc7\xac\x1c!\x01\x16\x8eH\xfe\x15\x85\xc5\xc9\xf8)\xe92<*{\x95D\xb62\xb7\xdc\x1e\xe4\xe13\x94[L\x84\xba!\xe3\xb1\x85\x11f\xfaK~\x83\xc1\xb15P\xca\x8e\xd2\x93\xa3<:\t\xbef\xef\xd0$\xcb\xb9w\xf9\xc6:\xd0@`I\xdd\xf5M\xed\x91\xba\xcc4\xbbh\xa8\xab\xa7p\x87\x82\xd7\'b\x14b\xf5\xc2\x8bH\xdbt*\x89\x12\x95M6\xf7\xeb\xf3\xf5\x1f\xe8\x95\xc6/\xe3R\x8a\xd8d\xa6\xb2t\x97\xfb~@`I\xdd\xf5M\xed\x91\xba\xcc4\xbbh\xa8\xab\xa7p\x87\x82\xd7\'b\x14b\xf5\xc2\x8bH\xdbt*\x89\x12\x95M6\xf7\xeb\xf3\xf5\xaeY\x99\xcaK\x93\xef\xda\xb5:\xb4\xf8\xe9\xc4\x9d\xcd@`I\xdd\xf5M\xed\x91{\xbb\x10\xde\xe3\x19\x7f\x93\xeaj]\xab\xb1\xfd\xad\x8a9\xdc\xe75\x94\xd4\xad\x9a\x03Z\x82]\x91\x83\xe5\xc9#\xf1\xd0\xac\x84lx\x82\xfc\xf5Zy\x0b\x03\xc3\xfb\xe5\t\xd4\xcc\x91{\xe5]a\xc8\xb4&\xb2\x9c\x1bk\xc8gA?C\x02`\x9c\xe6\xe5\xd6\x11ru/N@9\xf6\x0bj\xab\xa5\xea,\r\xe6@\x11\xe5\xd1\xb5\x88Q?z\xbbx\x9f7\xec\xa90koj\xce\x10P\x0f-\x9aw\xf2\xed\x12,..\xb7\xf4\xf2\x1f\x1f8<\x04\xf0"3`\x95/4\xdew"\xcb\x86\xd7v\xa1\x01[\x9d\xb2\x9c\x01\xb49}2\x1c\xc4\x12 \x00s\xb2\x96#\xe9\x98m\x83\xca\x0e$PV\xd56\xe5\x06jI\xf1\x8d\xb5\xed^+\xbd\xe9\xb4\x9d\xea\x88L3Td1\x9f\x08\xb3&v\xf1\xb6\\\xfe\xe3\xb1\xaa\xfd\x9c\x99a/\xe1&\x00s\xb2\x96#\xe9\x98m\xf3I\x92LV\xd4\xc1\xbd\xde\xbc\xdb\xa1\x02\xe7\x81\xceJ\x9b/\xc5~E\xd1\x8e\xba\x9e\x90\xea\x9d\xc9\xf5\xf0&v\xf1\xb6\\\xfe\xe3\xb1\xaa\xfd\x9c\x99a/\xe1&\x00s\xb2\x96#\xe9\x98m\xf3I\x92LV\xd4\xc1\xbd\xde\xbc\xdb\xa1\x02\xe7\x81\xce\xb3\xec\xb1Y\xe8Y\x04\x13\xed\x9dB\xbahK$\x88&v\xf1\xb6\\\xfe\xe3\xb1\xccc\xaakwPw\x00\xd8\x8b\x811`\xef\xda\xd2\xd5\xe13!w\xddWTmJ\x98.\xb8!\xf2\x19\xb9,\xa8\xed1b\xc0\x89n\xf1\xc8\xdd(\xd9k)\xa5s\xe1\xbfH\xbc\xbebp\x87\x82\xd7\'b\x14bK\xae\x0e\x15\xb0\xe9\xbf\x96@\xdf5/\x84\x90?\xa1J\x04\xda\xf6\xe3r\x8d`B\x83\x0e\x06lj\x8e\x96@`I\xdd\xf5M\xed\x91\x1d<\xba\xb2\x91L.Ij5EY\xc0\xc4E=\xf8)\x9d\x7f\xa6\xfc\x86# \x84\x1a7\xff\xa3m\xd2\xee.\xfd}\xb7\xd2S!~\x01\x1e?^\xf8\xad\xadN\xad&\x11j\xb2\xfd>\x14a\x03\xfbA$ $\x88\x8d\xd1\xb7\x9b\xbb\xe6\xc4\xfcM#v\xeb\xf6I\xe4\x0c\xc6\xd7\x8cC;M\x161\xfe%\xda=\xd5\xffKF:)\xf0y\x04\xd9w\xc6m\x10/A\x81\x98\x8e 2\x83\xefy\xbd\x12kf\x82\n\'\xa55S\xae\xc3K\xbf\x04P\xbb\xa4\x1d\x17O\x80\x11k\x7f\x0c-s\x00(.\x9b\x035G\xe5\xb4\x82Q\xd02\x8c\xaa#\xf1\xd0\xac\x84lx\x82\xb4\xfe\x81\x11\x163#H\xe5\t\xd4\xcc\x91{\xe5]\xc9\xc4\\\xc0?vB[\xe9K\x9b\xdb\xa5:\xa2\x98fa\x94\xaa\xf9\xa9\xa05@9\xf6\x0bj\xab\xa5\xea\xe9\x03a=[e\x0f\xcf\xdd2\x91\x12\x9e\xac@6\xa5?M\xf87\xab\x91\xb1\x8er0-\xacu\x8a\x1d\n\xf0\xcfb\xce\x11\x07fuF\x92\xda\x04\x9f\x10I@9\xf6\x0bj\xab\xa5\xea\xb3\n`\x1d\xb9\xc5\x81\x8a\xdd2\x91\x12\x9e\xac@6\xa5?M\xf87\xab\x91\xb1\x8er0-\xacu\x8a\x1d\n\xf0\xcfb\xce\x11\x07f\x98\x05\x1a\x05\x99H=\x7f@9\xf6\x0bj\xab\xa5\xea,\r\xe6@\x11\xe5\xd1\xb5\x9e\x87\xe9\xadPke\xe8j5EY\xc0\xc4E=P\xccs\xed\xfe\x91*\xd1 \x84\x1a7\xff\xa3m\xd2\xee.\xfd}\xb7\xd2S!\xbb\xed_\xd8\xd0e\xee\x1dN\xad&\x11j\xb2\xfd>\x14a\x03\xfbA$ $0\xab;\xa3\xcd\x11\xeeB\x1e\xd4h\xda3_\x85\x93\x87X\xc8\x86\\\xd6\xc5I1\xfe%\xda=\xd5\xffKF:)\xf0y\x04\xd9w\x96q\x9e+!Le:\xc1\x9d,0-\xa6\x07\x80&AKq\x7fZ\x9b6\xd5\xe13!w\xddWTmJ\x98.\xb8!\xf2\x19\xb9,\xa8\xed1b\xc0\x89\x11y\xca\x048\xb4G\x07\xa5s\xe1\xbfH\xbc\xbebp\x87\x82\xd7\'b\x14b\xa8\x10\x85$\x1fp\xfa\x169\xf5\xf0U\x90aQ\xf8Z\x88C+>sb\x1d\x8c\xbe\xd1~f&\xa7\xc2\x85`\xfe0z\xe7\x00A'
    decrypted_data = NativeUtils.decrypt(test_data, 5)
    print(decrypted_data)

    # --- DES 加解密示例 ---
    print("--- DES 加解密示例 ---")
    my_text = "Hello, Sogou! This is a test."
    key_type_des = 1

    # c: 加密并Base64编码
    encrypted_b64 = NativeUtils.encrypt_to_base64(my_text, key_type_des)
    print(f"原始明文: {my_text}")
    print(f"加密并Base64编码 (key_type={key_type_des}): {encrypted_b64}")

    # d: Base64解码并解密
    decrypted_text = NativeUtils.decrypt_base64(encrypted_b64, key_type_des)
    print(f"解密后的明文: {decrypted_text}")
    assert my_text == decrypted_text
    print("-" * 20)

    # --- MD5 签名示例 ---
    print("--- MD5 签名示例 ---")
    string_to_sign_f = "some_data_to_be_signed"
    key_type_md5 = 2
    signature_f = NativeUtils.sign_MD5(string_to_sign_f, key_type_md5)
    print(f"待签名字符串: {string_to_sign_f}")
    print(f"MD5签名 (key_type={key_type_md5}): {signature_f}")
    print("-" * 20)

    # --- 参数签名示例 ---
    print("--- 参数签名示例 ---")
    api_params = {
        "user": "test_user",
        "action": "login",
        "time": 1678886400,
        "app_version": "2.1.0"
    }
    secret_suffix = "a_secret_string_from_somewhere"
    signature_e = NativeUtils.sign_dict_MD5(api_params, secret_suffix, key_type_md5)

    # 手动构造签名原文以验证
    expected_sign_source = "action=login&app_version=2.1.0&time=1678886400&user=test_user" + secret_suffix
    print(f"API参数: {api_params}")
    print(f"附加字符串: {secret_suffix}")
    print(f"构造的签名原文: {expected_sign_source}")
    print(f"参数签名 (key_type={key_type_md5}): {signature_e}")
    # 验证e方法的实现是否正确
    assert signature_e == NativeUtils.sign_MD5(expected_sign_source, key_type_md5)
    print("-" * 20)

    # --- 获取固定密钥示例 ---
    print("--- 获取固定密钥示例 ---")
    fixed_key = NativeUtils.get_key()
    print(f"g() 获取的固定密钥字符串: {fixed_key.encode('latin-1').hex()}")
    print("-" * 20)
