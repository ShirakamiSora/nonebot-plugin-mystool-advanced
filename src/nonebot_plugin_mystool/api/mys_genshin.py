import asyncio
from typing import List, Optional, Tuple, Type, Dict

import httpx
import tenacity

from ..api.common import ApiResultHandler, is_incorrect_return, create_verification, \
    verify_verification
from ..model import BaseApiStatus, MissionStatus, MissionData, \
    MissionState, UserAccount, plugin_config, plugin_env, UserData
from ..utils import logger, generate_ds, \
    get_async_retry, get_validate




# 玩家原神账号信息,GET请求
URL_GENSHIN_ACCOUNT_INFO = "https://api-takumi-record.mihoyo.com/game_record/app/genshin/api/index?avatar_list_type=1&server=cn_gf01&role_id={}"
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
        'Host': ' api-takumi-record.mihoyo.com',
        'Connection': ' keep-alive',
        'x-rpc-tool_verison': ' v5.0.1-ys',
        'x-rpc-app_version': plugin_env.device_config.X_RPC_APP_VERSION,
        'User-Agent': ' Mozilla/5.0 (Linux; Android 12; SDY-AN00 Build/V417IR; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/95.0.4638.74 Safari/537.36 miHoYoBBS/2.75.2',
        'Accept': ' application/json, text/plain, */*',
        'x-rpc-device_name': plugin_env.device_config.X_RPC_DEVICE_NAME_ANDROID,
        'x-rpc-page': ' v5.0.1-ys_#/ys/role/all',
        'x-rpc-sys_version': ' 12',
        'x-rpc-client_type': ' 5',
        'Origin': ' https://webstatic.mihoyo.com',
        'X-Requested-With': ' com.mihoyo.hyperion',
        'Sec-Fetch-Site': ' same-site',
        'Sec-Fetch-Mode': ' cors',
        'Sec-Fetch-Dest': ' empty',
        'Referer': ' https://webstatic.mihoyo.com/',
        'Accept-Language': ' zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7',
        'Content-Type': ' application/json;charset=UTF-8'
    }

    def __init__(self, account: UserAccount, **kwargs):
        self.header["x-rpc-device_id"] = account.device_id_android
        for k, v in kwargs:
            self.header[k] = v
        
    
    def query(self, header, url, **kwargs):
        """
        通用查询
        ds:{
            参数类型:参数值
        }
        """
        retrying = get_async_retry(retry)
        retrying.retry = retrying.retry and tenacity.retry_if_result(lambda x: x is None)
        try:
            async for attempt in retrying:
                with attempt:
                    async with httpx.AsyncClient() as client:
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
                        if plugin_config.preference.geetest_url or user.geetest_url:
                            create_status, mmt_data = await create_verification(self.account)
                            if create_status:
                                if geetest_result := await get_validate(user, mmt_data.gt, mmt_data.challenge):
                                    if await verify_verification(mmt_data, geetest_result, self.account):
                                        logger.success(
                                            f"通用查询: 用户 {self.account.display_name} 人机验证通过")
                                        continue
                        else:
                            logger.info(
                                f"通用查询: 用户 {self.account.display_name} 未配置极验人机验证打码平台")
                        return MissionStatus(need_verify=True), None
                    elif api_result.retcode == 1008:
                        logger.warning(
                            f"通用查询: 用户 {self.account.display_name} 今日已经签到过了")
                        logger.debug(f"网络请求返回: {res.text}")
                        return MissionStatus(success=True, already_signed=True), 0
                    return api_result.data
        except tenacity.RetryError as e:
            if is_incorrect_return(e):
                logger.exception(f"通用查询: 服务器没有正确返回")
                logger.debug(f"网络请求返回: {res.text}")
                return MissionStatus(incorrect_return=True), None
            else:
                logger.exception("通用查询: 请求失败")
                return MissionStatus(network_error=True), None



    def query_genshin_account_info(self, account):
        """
        查询原神账号信息
        """

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
        flag = True
        for record in records:
            if record.game_id == game_id:
                try:
                    flag = False
                    params = {"role_id": record.game_role_id, "server": record.region}
                    headers = HEADERS_GENSHIN_STATUS_BBS.copy()
                    headers["x-rpc-device_id"] = account.device_id_android
                    headers["x-rpc-device_fp"] = account.device_id_android or generate_fp_locally()
                    headers["DS"] = generate_ds(params={"role_id": record.game_role_id, "server": record.region})
                    api_result = self.query(url=URL_GENSHIN_ACCOUNT_INFO, header=headers)
                except tenacity.RetryError as e:
                    if is_incorrect_return(e):
                        logger.exception(f"原神实时便笺: 服务器没有正确返回")
                        logger.debug(f"网络请求返回: {res.text}")
                    else:
                        logger.exception(f"原神实时便笺: 请求失败")





    
