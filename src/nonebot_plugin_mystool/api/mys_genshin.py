import asyncio
from typing import List, Optional, Tuple, Type, Dict

import httpx
import tenacity

from nonebot import require
require("nonebot_plugin_htmlrender")
from nonebot_plugin_htmlrender import html_to_pic, get_new_page, template_to_pic

from ..api.common import ApiResultHandler, is_incorrect_return, create_verification, \
    verify_verification
from ..model import BaseApiStatus, MissionStatus, MissionData, \
    MissionState, UserAccount, plugin_config, plugin_env, UserData, GenshinNote, GenshinNoteStatus, data_path
from ..utils import logger, generate_ds, \
    get_async_retry, get_validate
from ..api.common import genshin_note, get_game_record, starrail_note, get_mys_official_message, get_game_list
from ..utils import generate_device_id, logger, generate_ds, \
    get_async_retry, generate_seed_id, generate_fp_locally, html2img, get_local_images




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
    'x-rpc-device_name': 'HONOR%20SDY-AN00',
    'x-rpc-device_id':'e12a76c9-47c0-3dfc-ab91-dad20b0d77a1',
    x-rpc-device_fp 不对，需要post：https://public-data-api.mihoyo.com/device-fp/api/getFp去获取
    详细：https://github.com/UIGF-org/mihoyo-api-collect/blob/c1d92f10003f8842c2812ecaaccaae794024f288/hoyolab/login/password_hoyolab.md
    

    header = {
        'Host': 'api-takumi-record.mihoyo.com',
        'Connection': 'keep-alive',
        'x-rpc-tool_verison': 'v5.0.1-ys',
        'x-rpc-app_version': "2.75.2",
        'Accept': 'application/json, text/plain, */*',
        'x-rpc-device_name': 'iPhone',
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
        
    
    async def get_genshin_account(self):
        """
        获取账号原神相关信息
        """
        account = self.account
        game_record_status, records = await get_game_record(account)
        if not game_record_status:
            logger.info(f'获取米游社账号{account.display_name}游戏信息失败')
            return
        game_list_status, game_list = await get_game_list()
        if not game_list_status:
            logger.info(f'获取米游社账号{account.display_name}游戏列表失败')
            return 
        genshin_game_info = [x for x in game_list if x.en_name == 'ys'][0]
        # game_filter = filter(lambda x: x.en_name == 'ys', game_list)
        # game_info = next(game_filter, None)

        if not genshin_game_info:
            logger.info(f'获取米游社账号{account.display_name}下原神账号失败，可能是没有账号')
            return 
        else:
            game_id = genshin_game_info.id
        return [x for x in records if x.game_id == game_id][0]

    
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
        record = await self.get_genshin_account()
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


    async def query_genshin_account_characters_info(self):
        """
        查询账号下角色信息
        """
        account = self.account
        record = await self.get_genshin_account()
        try:
            content = {"role_id": record.game_role_id, "server": record.region, "sort_type":"1"}
            headers = self.header.copy()
            headers["x-rpc-device_id"] = account.device_id_ios.lower()
            headers["x-rpc-device_fp"] = account.device_fp or generate_fp_locally()
            headers["DS"] = generate_ds(data=content)
            api_result = await self.query(url=URL_GENSHIN_ACCOUNT_CHARACTERS_INFO, header=headers, method='POST', content=content)
            character_0 = api_result['list'][0]
            result = f"第一个角色信息为:id{character_0['id']},角色姓名:{character_0['name']},等级:{character_0['level']}"
            return result
        except:
            logger.exception(f'查询账号角色信息失败')


    def character_name_to_id(self, character_names:list[str]) -> list[str]:
        """
        将传入的角色名称转换为对应的id
        """
        import json
        try:
            items_id_path = data_path / "items_id.json"
            with open(items_id_path, 'r', encoding='utf-8') as file:
                data = json.load(file)
        except:
            logger.debug(f'读取item_id.json文件失败')

        return [str(data[c]) if c in data else '' for c in character_names ]
    
    async def query_genshin_character_detail_info(self, character_names:list[str] = []):
        """
        查询账号下角色详细信息，包括圣遗物等
        调整参数可以用来查询多个角色
        """
        if not character_names:
            return f'未传入角色'
        character_ids = self.character_name_to_id(character_names)
        for c in character_ids:
            if not c:
                return f'传入的角色中有未查询到的角色，请核实角色名称'
        account = self.account
        record = await self.get_genshin_account()
        try:
            content = {"role_id": record.game_role_id, "server": record.region, "character_ids":character_ids}
            headers = self.header.copy()
            headers["x-rpc-device_id"] = account.device_id_ios.lower()
            headers["x-rpc-device_fp"] = account.device_fp or generate_fp_locally()
            headers["DS"] = generate_ds(data=content)
            # logger.debug(f'传入的content为:{content}\n传入的header为:{headers}\n')
            api_result = await self.query(url=URL_GENSHIN_ACCOUNT_CHARACTER_DETAIL, header=headers, method='POST', content=content)
            character_0 = api_result['list'][0]
            property_map = api_result['property_map']
            # result = f"第一个角色信息为:id{character_0['base']['id']},角色姓名:{character_0['base']['name']},等级:{character_0['base']['level']}"
            return character_0, property_map
        except:
            logger.exception(f'查询账号角色信息失败')


    async def get_one_character_info_by_pic(self, character_name:str) -> bytes:
        """
        查询单个角色信息并转换成图片形式
        返回图片字节流
        """
        character_info, property_map = await self.query_genshin_character_detail_info([character_name])
        character_id = character_info['base']['id']
        # 先将所有图片转换成本地路径
        # 角色背景图
        character_bgp_dir = data_path / f"genshin_template/data/{character_id}"
        local_character_bgp_link = await get_local_images([character_info['base']['image']], character_bgp_dir)
        local_character_bgp_link = local_character_bgp_link[0]
        # 角色元素图标,先不传，没找到链接
        # character_element_img_dir = str(data_path) + f'genshin_template/data/element'
        # local_character_element_img_link = await get_local_images([character_info['base']['image']], character_bgp_dir)

        # 角色属性
        # 一共28条属性，5+7+16
        all_properties = character_info['base_properties'] + character_info['extra_properties'] + character_info['element_properties']

        character_properties = {
            str(x['property_type']):x for x in all_properties
        }
        character_properties_icon_dir = data_path / f'genshin_template/data/charatcer_properties'
        for k, v in character_properties.items():
            character_properties[k]['name'] = property_map.get(k)['name']
            # 直接转成本地绝对路径了
            character_properties[k]['icon'] = await get_local_images([property_map.get(k)['icon']], character_properties_icon_dir)
            character_properties[k]['icon'] = character_properties[k]['icon'][0]
            # logger.debug(f"属性图片本地绝对路径：{character_properties[k]['icon']}")
            

        # 角色技能图标
        character_skill_img_dir = data_path / f'genshin_template/data/{character_id}/skill'
        c_skills_icon = [x['icon'] for x in character_info['skills']]
        local_character_skill_img_link = await get_local_images(c_skills_icon, character_skill_img_dir)
        character_skills = [{"name":x['name'], "img":local_character_skill_img_link[i]} for i, x in enumerate(character_info['skills'])]
        
        # 武器图标
        weapon_img_dir = data_path / f'genshin_template/data/weapon'
        local_weapon_img_link = await get_local_images([character_info['weapon']['icon']], weapon_img_dir)
        local_weapon_img_link = local_weapon_img_link[0]
        
        # 圣遗物
        relic_img_dir = data_path / f'genshin_template/data/relics'
        relics_icon = [x['icon'] for x in character_info['relics']]
        local_relic_img_link = await get_local_images(relics_icon, relic_img_dir)
        character_info['weapon']['main_property_name'] = property_map.get(str(character_info['weapon']['main_property']['property_type']))['name']
        character_info['weapon']['sub_property_name'] = property_map.get(str(character_info['weapon']['sub_property']['property_type']))['name']
        # 将全部的信息做整理，只传递有用到的
        relics = []
        for i, relic in enumerate(character_info['relics']):
            relics.append({
                "info":{
                    "name":relic['name'],
                    "level":relic['level'],
                    "img":local_relic_img_link[i]
                },
                "main":{
                    "name":property_map.get(str(relic['main_property']['property_type']))['name'],
                    "value":relic['main_property']['value']
                },
                "sub":[
                    {
                        "name":property_map.get(str(sub['property_type']))['name'],
                        "value":sub['value'],
                        "times":sub['times']
                    }
                    for sub in relic['sub_property_list']
                ]
            })
        
        res = {
            "character_bg":local_character_bgp_link,
            "charatcer_element":'',
            "character_skills":character_skills,
            "character":character_info['base'],
            "weapon_img":local_weapon_img_link,
            "weapon":character_info['weapon'],
            "relics":relics,
            "character_properties":character_properties
        }

        return await self.genshin_generate_character_pic(res)

    async def genshin_generate_character_pic(self, content:dict) -> bytes:
        """
        利用获取到的角色数据生成图片,先传默认
        """
        # path = data_path / "genshin_template/template.html"
        # path = path.as_uri()
        from pathlib import Path
        # 获取当前脚本的父文件夹
        parent_dir = Path(__file__).parent.parent

        # 获取同级文件夹（例如data）中的文件
        file_path = parent_dir / 'template'

        # 转换为绝对路径
        absolute_path = file_path.resolve()
        logger.debug(f'html模板路径:{absolute_path}')



        # async with get_new_page() as page:
        #     await page.goto(path)
        #     pic = await page.screenshot(full_page=True)

        pic = await template_to_pic(
            template_path=absolute_path, 
            template_name='template.html',
            templates=content
        )
        return pic



