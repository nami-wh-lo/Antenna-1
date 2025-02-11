from ipaddress import IPv4Address
import socket

from twisted.internet import reactor, defer
from twisted.names import client, dns, error, server

# 导入twisted的相关模块
import os
import re
import sys
import fnmatch
import django
from itertools import cycle

from twisted.names.dns import DNSDatagramProtocol

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__) + "../../../../../")
sys.path.append(PROJECT_ROOT)
os.environ['DJANGO_SETTINGS_MODULE'] = 'antenna.settings'
django.setup()

from modules.config import setting
from twisted.internet import reactor
from twisted.names import dns, server
from utils.helper import send_message, send_email_message
from modules.message.constants import MESSAGE_TYPES
from modules.config.models import DnsConfig
from modules.message.models import Message
from modules.task.models import TaskConfig, TaskConfigItem
from modules.template.depend.base import BaseTemplate


class DNSServerFactory(server.DNSServerFactory):
    def handleQuery(self, message, protocol, address):
        # 感谢 suppress\excessive 同学发现python3.6版本运行bug，已fix
        sock_type = protocol.transport.socket.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
        if sock_type == socket.SOCK_DGRAM:
            self.peer_address = address[0]
        elif sock_type == socket.SOCK_DGRAM:
            self.peer_address = IPv4Address('UDP', *address)[0]
        else:
            raise ("Unexpected socket type %r" % protocol.transport.socket.type)
        # Make peer_address available to resolvers that support that attribute
        for resolver in self.resolver.resolvers:
            if hasattr(resolver, 'peer_address'):
                resolver.peer_address = self.peer_address
        return server.DNSServerFactory.handleQuery(self, message, protocol, address)


class DynamicResolver(object):
    """
    A resolver which calculates the answers to certain queries based on the
    query type and name.
    """

    def __init__(self):
        super().__init__()
        # 初始化变量
        self._peer_address = None
        self.dns_config = {}
        dns_recoed = DnsConfig.objects.all()
        self.dns_config_domain = [_dns.domain for _dns in dns_recoed]
        for _dns in dns_recoed:
            self.dns_config[_dns.domain] = cycle(_dns.value)

    @property
    def peer_address(self):
        return self._peer_address

    @peer_address.setter
    def peer_address(self, value):
        self._peer_address = value

    def _dynamicResponseRequired(self, query):
        """
        Check the query to determine if a dynamic response is required.
        A:1
        AAAA:28
        CNAME:5
        MX:15
        """
        return True

    def _doDynamicResponse(self, query):
        """
        Calculate the response to a query.
        """
        answers = []
        # 获取查询的域名和类型
        name = query.name.name
        addr = self.peer_address
        _type = query.type
        self.dns_config_domain.sort(key=lambda x: x.startswith("*"))  # 进行排序
        print("请求解析域名：", name.decode("utf-8"), flush=True)
        for domain in self.dns_config_domain:
            print("匹配域名", domain, "匹配结果:", fnmatch.fnmatch(name.decode("utf-8"), domain))
            if fnmatch.fnmatch(name.decode("utf-8").lower(), domain.lower()):
                answers.append(dns.RRHeader(
                    name=name,
                    payload=dns.Record_A(address=bytes(next(self.dns_config[domain]), encoding="utf-8")), ttl=0))
                # 存储数据
                udomain = re.findall(r'\.?([^\.]+)\.%s' % setting.DNS_DOMAIN.strip("*."), name.decode("utf-8").lower())
                if udomain:
                    task_config_item = TaskConfigItem.objects.filter(task_config__key__iexact=udomain[0],
                                                                     task__status=1).first()
                    if task_config_item and task_config_item.template.name == "DNS":
                        username = task_config_item.task.user.username
                        Message.objects.create(domain=name.decode("utf-8"), message_type=MESSAGE_TYPES.DNS,
                                               remote_addr=addr,
                                               task_id=task_config_item.task_id,
                                               template_id=task_config_item.template_id)
                        print("完成保存")
                        send_email_message(username, addr)
                        send_message(url=name.decode("utf-8"), remote_addr=addr, uri='', header='',
                                     message_type=MESSAGE_TYPES.DNS, content='', task_id=task_config_item.task_id)
                break
        authority = []
        additional = []
        return answers, authority, additional

    def query(self, query, timeout=None):
        """
        Check if the query should be answered dynamically, otherwise dispatch to
        the fallback resolver.
        """
        if self._dynamicResponseRequired(query):
            return defer.succeed(self._doDynamicResponse(query))
        else:
            return defer.fail(error.DomainError())


def main():
    """
    Run the server.
    """
    factory = DNSServerFactory(clients=[DynamicResolver()])
    protocol = DNSDatagramProtocol(controller=factory)
    reactor.listenUDP(53, protocol, interface="0.0.0.0")

    reactor.run()


class DnsTemplate(BaseTemplate):
    info = [{
        "template_info": {
            "name": "DNS",  # 组件名
            "title": "DNS协议监听组件",  # 组件展示标题名
            "author": "bios000",  # 组件作者
            "type": 1,  # 组件类型，1是监听0是利用
            "desc": "",  # 组件介绍
            "desc_url": "",  # 组件使用说明链接
            "choice_type": 0,  # 组件选择类型0是单选，1是多选
            "payload": "{key}.{dns_domain}",  # 组件利用实例
            "file_name": "dnslog.py",

        },
        "item_info": [{
            "name": "dns_log",
            "config": [],

        }]}]

    def __init__(self):
        super().__init__()


if __name__ == '__main__':
    raise SystemExit(main())
