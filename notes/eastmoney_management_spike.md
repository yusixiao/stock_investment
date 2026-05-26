# EastMoney 管理层数据源 spike 笔记

测试代码:600519.SH


## 600519.SH
### datacenter — 600519.SH
- ✗ RPT_F10_BASIC_OFFICERS: 报表配置不存在,RPT_F10_BASIC_OFFICERS
- ✗ RPT_F10_OFFICER: 报表配置不存在,RPT_F10_OFFICER
- ✗ RPT_F10_OFFICERS: 报表配置不存在,RPT_F10_OFFICERS
- ✗ RPT_F10_BASIC_OFFICER: 报表配置不存在,RPT_F10_BASIC_OFFICER
- ✗ RPT_F10_PERSONNEL_INFO: 报表配置不存在,RPT_F10_PERSONNEL_INFO
- ✗ RPT_F10_HOLDER_NUMOFFICERHOLD: 报表配置不存在,RPT_F10_HOLDER_NUMOFFICERHOLD
- ✗ RPT_EXECUTIVE_HOLDCHANGE: 报表配置不存在,RPT_EXECUTIVE_HOLDCHANGE
- ✗ RPT_F10_OFFICERHOLD: 报表配置不存在,RPT_F10_OFFICERHOLD
- ✗ RPT_OFFICERSHOLDS: 报表配置不存在,RPT_OFFICERSHOLDS
### emweb PageAjax — 600519.SH
- ✅ **https://emweb.eastmoney.com/CompanyManagement** top_keys=`['gglb', 'cgbd']`
- ⚠ https://emweb.eastmoney.com/ManagerInfo: 非 JSON status=200 head=`ï»¿<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
    <title>æ F10èµæ</title>
    <style type="te`
- ⚠ https://emweb.eastmoney.com/PersonInfo: 非 JSON status=200 head=`ï»¿<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
    <title>æ F10èµæ</title>
    <style type="te`
- ⚠ https://emweb.eastmoney.com/GGRYJS: 非 JSON status=200 head=`ï»¿<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
    <title>æ F10èµæ</title>
    <style type="te`
- https://f10.eastmoney.com/CompanyManagement: EXC `403 Client Error: Forbidden for url: https://f10.eastmoney.com/PC_HSF10/CompanyManagement/PageAjax?code=SH600519`
- https://f10.eastmoney.com/ManagerInfo: EXC `403 Client Error: Forbidden for url: https://f10.eastmoney.com/PC_HSF10/ManagerInfo/PageAjax?code=SH600519`
- https://f10.eastmoney.com/PersonInfo: EXC `403 Client Error: Forbidden for url: https://f10.eastmoney.com/PC_HSF10/PersonInfo/PageAjax?code=SH600519`
- https://f10.eastmoney.com/GGRYJS: EXC `403 Client Error: Forbidden for url: https://f10.eastmoney.com/PC_HSF10/GGRYJS/PageAjax?code=SH600519`