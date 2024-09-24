import asyncio
from typing import List, Optional, Tuple, Type, Dict

import httpx
import tenacity

from ..api.common import ApiResultHandler, is_incorrect_return, create_verification, \
    verify_verification
from ..model import BaseApiStatus, MissionStatus, MissionData, \
    MissionState, UserAccount, plugin_config, plugin_env, UserData, GenshinNote, GenshinNoteStatus
from ..utils import logger, generate_ds, \
    get_async_retry, get_validate
from ..api.common import genshin_note, get_game_record, starrail_note, get_mys_official_message, get_game_list
from ..utils import generate_device_id, logger, generate_ds, \
    get_async_retry, generate_seed_id, generate_fp_locally




# 玩家原神账号信息,GET请求
URL_GENSHIN_ACCOUNT_INFO = "https://api-takumi-record.mihoyo.com/game_record/app/genshin/api/index"
# 玩家账号下原神角色信息,post
URL_GENSHIN_ACCOUNT_CHARACTERS_INFO = "https://api-takumi-record.mihoyo.com/game_record/app/genshin/api/character/list"
# 玩家单原神角色详细信息，包括圣遗物等,POST
URL_GENSHIN_ACCOUNT_CHARACTER_DETAIL = "https://api-takumi-record.mihoyo.com/game_record/app/genshin/api/character/detail"


# header
class GenshinRequest:
    """
    原神通用请求头
    """
    
    header = {
        'Host': 'api-takumi-record.mihoyo.com',
        'Connection': 'keep-alive',
        'x-rpc-tool_verison': 'v4.2.2-ys',
        'x-rpc-app_version': plugin_env.device_config.X_RPC_APP_VERSION,
        'Accept': 'application/json, text/plain, */*',
        'x-rpc-device_name': plugin_env.device_config.X_RPC_DEVICE_NAME_MOBILE,
        'x-rpc-device_model':plugin_env.device_config.X_RPC_DEVICE_MODEL_MOBILE,
        'x-rpc-page': 'v4.2.2-ys_#/ys',
        'User-Agent':plugin_env.device_config.USER_AGENT_MOBILE,
        'x-rpc-sys_version': '12',
        'x-rpc-client_type': '5',
        'Origin': 'https://webstatic.mihoyo.com',
        'X-Requested-With': 'com.mihoyo.hyperion',
        'Sec-Fetch-Site': 'same-site',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Dest': 'empty',
        'Referer': 'https://webstatic.mihoyo.com/',
        'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7',
        'Content-Type': 'application/json;charset=UTF-8'
    }

    """
    x-rpc-device_fp 不对，需要post：https://public-data-api.mihoyo.com/device-fp/api/getFp去获取
    详细：https://github.com/UIGF-org/mihoyo-api-collect/blob/c1d92f10003f8842c2812ecaaccaae794024f288/hoyolab/login/password_hoyolab.md
    
    header = {
        'Host': 'api-takumi-record.mihoyo.com',
        'Connection': 'keep-alive',
        'x-rpc-tool_verison': 'v5.0.1-ys',
        'x-rpc-app_version': "2.75.2",
        'Accept': 'application/json, text/plain, */*',
        'x-rpc-device_name': 'HONOR%20SDY-AN00',
        'x-rpc-device_id':'e12a76c9-47c0-3dfc-ab91-dad20b0d77a1',
        'x-rpc-page': 'v5.0.1-ys_#/ys',
        'x-rpc-device_fp':'38d7fea11fc30',
        'User-Agent':'Mozilla/5.0 (Linux; Android 12; SDY-AN00 Build/V417IR; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/95.0.4638.74 Safari/537.36 miHoYoBBS/2.75.2',
        'x-rpc-sys_version': '12',
        'x-rpc-client_type': '5',
        'Origin': 'https://webstatic.mihoyo.com',
        'X-Requested-With': 'com.mihoyo.hyperion',
        'Sec-Fetch-Site': 'same-site',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Dest': 'empty',
        'Referer': 'https://webstatic.mihoyo.com/',
        'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7',
        'Content-Type': 'application/json;charset=UTF-8',
        'Accept-Encoding':'gzip, deflate'
    }
    """
    

    def __init__(self, account: UserAccount, **kwargs):
        self.header["x-rpc-device_id"] = account.device_id_ios
        self.account = account
        for k, v in kwargs:
            self.header[k] = v
        
    
    async def query(self, header, url, method = 'GET', content=None, params=None, **kwargs):
        """
        通用查询
        ds:{
            参数类型:参数值
        }
        """
        retrying = get_async_retry(True)
        retrying.retry = retrying.retry and tenacity.retry_if_result(lambda x: x is None)
        print(f'cookie为:{self.account.cookies.dict(v2_stoken=True, cookie_type=True)}')
        try:
            async for attempt in retrying:
                with attempt:
                    async with httpx.AsyncClient() as client:
                        if method == 'GET':
                            res = await client.get(
                                url,
                                headers=header,
                                params=params,
                                timeout=plugin_config.preference.timeout,
                                cookies=self.account.cookies.dict(v2_stoken=True, cookie_type=True)
                            )
                        elif method == 'POST':
                            res = await client.post(
                                url,
                                headers=header,
                                json=content,
                                timeout=plugin_config.preference.timeout,
                                cookies=self.account.cookies.dict(v2_stoken=True, cookie_type=True)
                            )
                    api_result = ApiResultHandler(res.json())
                    if api_result.login_expired:
                        logger.error(
                            f"通用查询失败")
                        logger.debug(f"网络请求返回: {res.text}")
                        return MissionStatus(login_expired=True), None
                    elif api_result.invalid_ds:
                        logger.error(
                            f"通用查询: 用户 {self.account.display_name} DS 校验失败")
                        logger.debug(f"网络请求返回: {res.text}")
                        return MissionStatus(invalid_ds=True), None
                    elif api_result.retcode == 1034:
                        logger.error(
                            f"通用查询: 用户 {self.account.display_name} 需要完成人机验证")
                        logger.debug(f"网络请求返回: {res.text}")
                    elif api_result.retcode == 1008:
                        logger.warning(
                            f"通用查询: 用户 {self.account.display_name} 今日已经签到过了")
                        logger.debug(f"网络请求返回: {res.text}")
                        return MissionStatus(success=True, already_signed=True), 0
                    print(f'请求返回{api_result}')
                    return api_result.data
        except tenacity.RetryError as e:
            if is_incorrect_return(e):
                logger.exception(f"通用查询: 服务器没有正确返回")
                logger.debug(f"网络请求返回: {res.text}")
                return MissionStatus(incorrect_return=True), None
            else:
                logger.exception("通用查询: 请求失败")
                return MissionStatus(network_error=True), None



    async def query_genshin_account_info(self):
        """
        查询原神账号信息
        """
        account = self.account
        game_record_status, records = await get_game_record(account)
        if not game_record_status:
            return GenshinNoteStatus(game_record_failed=True), None
        game_list_status, game_list = await get_game_list()
        if not game_list_status:
            return GenshinNoteStatus(game_list_failed=True), None
        game_filter = filter(lambda x: x.en_name == 'ys', game_list)
        game_info = next(game_filter, None)
        if not game_info:
            return GenshinNoteStatus(no_genshin_account=True), None
        else:
            game_id = game_info.id
        for record in records:
            if record.game_id == game_id:
                try:
                    params = {"role_id": record.game_role_id, "server": record.region, "avatar_list_type":"1"}
                    headers = self.header.copy()
                    headers["x-rpc-device_id"] = account.device_id_ios.lower()
                    headers["x-rpc-device_fp"] = account.device_fp or generate_fp_locally()
                    headers["DS"] = generate_ds(params=params)
                    api_result = await self.query(url=URL_GENSHIN_ACCOUNT_INFO, header=headers, method='GET', params=params)
                    print(f'请求头为:{headers}, url:{URL_GENSHIN_ACCOUNT_INFO}, param:{params}')
                    characters = [f"{x['actived_constellation_num']}命{x['rarity']}星{x['level']}级角色{x['name']}-好感{x['fetter']}\n" for x in api_result['avatars']]
                    result = f"""
                        "玩家基础信息":
                            "玩家昵称":{api_result['role']['nickname']},
                            "玩家账号的服务器名称":{api_result['role']['region']},
                            "玩家的冒险等级":{api_result['role']['level']},
                        "玩家拥有的角色的信息":{characters},
                        "其他游戏信息":
                            "活跃天数":{api_result['stats']['active_day_number']},
                            "已有角色数量":{api_result['stats']['avatar_number']},
                            "当前深渊层数":{api_result['stats']['spiral_abyss']}
                    """
                    return result
                except tenacity.RetryError as e:
                    if is_incorrect_return(e):
                        logger.exception(f"原神实时便笺: 服务器没有正确返回")
                    else:
                        logger.exception(f"原神实时便笺: 请求失败")





    
