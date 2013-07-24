#!/usr/bin/python
import sys
import argparse
import multiprocessing
import termcolor as T
from expt import Expt
from time import sleep
from host import *
from site_config import *
import os

parser = argparse.ArgumentParser(description="Memcached test for various rate limiters.")

parser.add_argument('--htb-mtu',
                    dest="htb_mtu",
                    help="HTB MTU parameter.",
                    default=1500)

parser.add_argument('--mtu',
                    help="MTU parameter.",
                    default=1500)

parser.add_argument('--exptid',
                    dest="exptid",
                    help="Experiment ID",
                    default=None)

parser.add_argument('--outdir',
                    dest="outdir",
                    help="Directory to store output.",
                    required=True)

parser.add_argument('--rl',
                    dest="rl",
                    help="Which rate limiter to use",
                    choices=["htb", "qfq", "none"],
                    default="")

parser.add_argument('--time', '-t',
                    dest="t",
                    type=int,
                    help="Time to run the experiment",
                    default=60)

parser.add_argument('--servers',
                    dest="servers",
                    help="Memcached servers to run tests",
                    nargs="+", default=config['DEFAULT_MC_SERVERS'])

parser.add_argument('--clients',
                    dest="clients",
                    help="Memcached clients to run tests",
                    nargs="+", default=config['DEFAULT_MC_CLIENTS'])

parser.add_argument('--sniffer',
                    dest="sniffer",
                    help="The sniffer machine to capture packet timings",
                    default='')

parser.add_argument('--rate',
                    dest="rate",
                    type=int,
                    help="Rate limit for each tenant's server-client traffic",
                    default=1000)

parser.add_argument('--mcrate',
                    dest="mcrate",
                    help="mcperf: Request generation rate from each tenant's "
                         "client to a server",
                    type=int,
                    default=500)

parser.add_argument('--mcexp',
                    dest="mcexp",
                    help="mcperf: Inter-req arrival time exponential",
                    action="store_true",
                    default=False)

parser.add_argument('--mcsize',
                    dest="mcsize",
                    help="mcperf: Size of requests",
                    type=int,
                    default=1024)

parser.add_argument('--mcworkload',
                    dest="mcworkload",
                    help="mcperf: Workload type (get/set)",
                    default="get")

parser.add_argument('--mcnconn',
                    dest="mcnconn",
                    help="mcperf: # of TCP connections for each memcached-mcperf pair",
                    type=int,
                    default=2)

parser.add_argument('--num_tenants',
                    dest="num_tenants",
                    type=int,
                    help="Number of cloud tenants to emulate on each server",
                    default=1)

parser.add_argument('--startport',
                    dest="startport",
                    type=int,
                    default=5000)

args = parser.parse_args()


def e(s, tmpdir="/tmp"):
    if s:
        return os.path.join(tmpdir, args.exptid, s)
    else:
        return os.path.join(tmpdir, args.exptid)


class MemcachedCluster(Expt):

    def start_memcached(self, hlist, mem=1024, port=5000, threads=1, cpus=[1]):
        cmd = "taskset -c %s " % ",".join([str(x) for x in cpus])
        cmd += "memcached -m %d " % mem
        cmd += "-p %d " % port
        cmd += "-u nobody "
        cmd += "-t %d" % threads
        for h in hlist.lst:
            h.cmd_async(cmd)


    def start_mcperf(self, hclient, server_ip, tenant_id="0_1", client_id="0_1",
                     port=5000, time=60, nconn=1, mcrate=500, mcexp=False,
                     workload="get", mcsize=1024, cpus=[1], dir="/tmp"):

        # Divide rate equally among connections from this mcperf instance to a
        # particular server
        if mcexp:
            rate = "e%.5f" % (1.0 / (float(mcrate) / nconn))
        else:
            rate = "%d" % (mcrate / nconn)

        N = mcrate * time

        cmd = "taskset -c %s " % ",".join([str(x) for x in cpus])
        cmd += "mcperf -s %s " % server_ip
        cmd += "-p %d " % port
        cmd += "--sizes d%d " % mcsize
        cmd += "--num-calls %d " % N
        cmd += "--call-rate %s " % rate
        cmd += "--num-conns %d " % nconn
        cmd += "--conn-rate %d " % nconn
        cmd += "-m %s " % workload
        cmd += "-H -T %d " % time
        cmd += "> %s/mcperf-t%s_-c%s-%s.txt" % (dir, tenant_id,
                                                client_id, server_ip)
        hclient.cmd_async(cmd)


    def start(self):
        sniffer = self.opts("sniffer")

        hservers = HostList()
        hclients = HostList()
        hlist = HostList()
        hsniffer = Host(sniffer)

        self.log(T.colored("Servers:---", "green"))
        for ip in self.opts("servers"):
            h = Host(ip)
            hservers.append(h)
            hlist.append(h)
            self.log(T.colored(ip, "green"))

        self.log(T.colored("Clients:---", "yellow"))
        for ip in self.opts("clients"):
            h = Host(ip)
            hclients.append(h)
            hlist.append(h)
            self.log(T.colored(ip, "yellow"))

        # Reset/clear state on servers and clients
        hlist.rmrf(e(""))
        hlist.mkdir(e("logs"))

        # Log the servers and clients used for the experiment
        local_cmd("mkdir -p %s/logs" % self.opts("outdir"))
        hostsfile = "%s/logs/hostsfile.txt" % self.opts("outdir")
        hostsfd = open(hostsfile, 'w')
        hostsfd.write("Servers:\n")
        for ip in self.opts("servers"):
            hostsfd.write("  " + ip + "\n")
        hostsfd.write("Clients:\n")
        for ip in self.opts("clients"):
            hostsfd.write("  " + ip + "\n")
        hostsfd.close()

        if sniffer:
            hsniffer.rmrf(e("", tmpdir=config['SNIFFER_TMPDIR']))
            hsniffer.mkdir(e("logs", tmpdir=config['SNIFFER_TMPDIR']))
            hsniffer.cmd("killall -9 %s" % config['SNIFFER'])

        hlist.rmmod()
        hlist.killall("udp")
        hlist.stop_trafgen()
        hlist.remove_qdiscs()
        hlist.cmd("sudo service memcached stop")
        if config['NIC_VENDOR'] == "Intel":
            hlist.clear_intel_hw_rate_limits(config['NIC_HW_QUEUES'])
            sleep(1)
        elif config['NIC_VENDOR'] == "Mellanox":
            hlist.clear_mellanox_hw_rate_limits()
            sleep(1)

        hlist.configure_tcp_limit_output_bytes()

        # Start memcached on servers - one instance for each tenant, pinned to a
        # different CPU core
        start_port = self.opts("startport")
        avail_cpus = [ x for x in xrange(0, config['NUM_CPUS'])
                             if x not in config['EXCLUDE_CPUS'] ]
        for tenant in xrange(0, self.opts("num_tenants")):
            self.start_memcached(hservers, mem = 1024,
                                 port = start_port + tenant,
                                 threads = 1,
                                 cpus = [avail_cpus[tenant]])

        # Configure rate limits
        # On server, configure separate rate limit to each tenant's client
        # On client, configure separate rate limit to each tenant's server
        '''
        TODO(siva): Script up the rate limiter configuration
        '''

        hlist.start_cpu_monitor(e('logs'))
        hlist.start_bw_monitor(e('logs'))
        #if self.opts("rl") == "qfq":
        #    self.client.start_qfq_monitor(e('logs'))
        hlist.start_mpstat(e('logs'))
        hlist.set_mtu(self.opts("mtu"))
        if sniffer:
            hsniffer.start_sniffer_delayed(e('logs', tmpdir=config['SNIFFER_TMPDIR']),
                    board=0, delay=config['SNIFFER_DELAY'],
                    duration=config['SNIFFER_DURATION'])
        sleep(1)

        # Start mcperf clients to generate requests. For each (tenant, server)
        # pair, create a separate mcperf instance. This is required since mcperf
        # does not have an option to send requests randomly to the available
        # memcached servers.
        for tenant in xrange(0, self.opts("num_tenants")):
            for hserver in hservers.lst:
                server_ip = socket.gethostbyname(hserver.hostname())
                for (cli_id, hclient) in enumerate(hclients.lst):

                    # Index of tenant and client connecting to this particular
                    # server for this tenant.
                    tenant_id = "%d_%d" % (tenant, self.opts("num_tenants"))
                    client_id = "%d_%d" % (cli_id, len(hclients.lst))

                    self.start_mcperf(hclient, server_ip, tenant_id, client_id,
                                      port = start_port + tenant,
                                      time = self.opts("t"),
                                      nconn = self.opts("mcnconn"),
                                      mcrate = self.opts("mcrate"),
                                      mcexp = self.opts("mcexp"),
                                      workload = self.opts("mcworkload"),
                                      mcsize = self.opts("mcsize"),
                                      cpus = [avail_cpus[tenant]],
                                      dir=e('logs'))

        self.hservers = hservers
        self.hclients = hclients
        self.hlist = hlist
        self.hsniffer = hsniffer


    def stop(self):
        self.hlist.killall("memcached")
        if self.opts("sniffer"):
            self.hsniffer.copy_local(e('', tmpdir=config['SNIFFER_TMPDIR']),
                                    self.opts("exptid") + "-snf",
                                    tmpdir=config['SNIFFER_TMPDIR'])
        self.hlist.copy_by_host(e('logs'), self.opts("outdir") + "/logs",
                                self.opts("exptid"))
        if config["NIC_VENDOR"] == "Intel":
            self.hlist.clear_intel_hw_rate_limits(config['NIC_HW_QUEUES'])
        elif config['NIC_VENDOR'] == "Mellanox":
            self.hlist.clear_mellanox_hw_rate_limits()


MemcachedCluster(vars(args)).run()