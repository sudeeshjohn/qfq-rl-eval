
import paramiko
from subprocess import Popen
import termcolor as T
import os
import socket
from time import sleep
from site_config import *
import pexpect
import math


class HostList(object):
    def __init__(self, *lst):
        self.lst = list(lst)

    def append(self, host):
        self.lst.append(host)

    def __getattribute__(self, name, *args):
        try:
            return object.__getattribute__(self, name)
        except AttributeError:
            ret = lambda *args: map(lambda h: h.__getattribute__(name)(*args), self.lst)
            return ret

    def __iter__(self):
        return self.lst

def local_cmd(c):
    print T.colored(c, "green")
    p = Popen(c, shell=True)
    p.wait()

def controladdr(addr):
    # TODO: this is a simple mapping scheme from the 10GbE
    # interface hostname to the control interface hostname.
    # e10 -> l10.  We may want a general mapping here.
    return addr.replace('e', 'l')

class ShellWrapper:
    def __init__(self, chan):
        self.chan = chan

    def cmd_async(self, cmd):
        self.chan.send("(%s;) &\n" % cmd)

    def cmd(self, c):
        self.chan.send(c)
        self.chan.recv_ready()
        return self.chan.recv(10**6)

class SSHWrapper:
    def __init__(self, ssh):
        self.ssh = ssh

    def cmd_async(self, cmd):
        cmd = "(%s;) &" % cmd
        self.ssh.sendline(cmd)

    def cmd(self, c):
        self.ssh.sendline(c)
        self.ssh.expect(config['SHELL_PROMPT'])

class Host(object):
    _ssh_cache = {}
    _shell_cache = {}
    def __init__(self, addr):
        self.addr = addr
        self.sshaddr = controladdr(addr)
        # List of processes spawned async on this host
        self.procs = []
        self.delay = False
        self.delayed_cmds = []
        self.dryrun = False

    def set_dryrun(self, state=True):
        self.dryrun = state

    def get(self):
        ssh = Host._ssh_cache.get(self.sshaddr, None)
        if ssh is None:
            ssh = pexpect.spawn("ssh %s" % self.sshaddr, timeout=120)
            ssh.expect(config['SHELL_PROMPT'])
            Host._ssh_cache[self.sshaddr] = ssh
        return ssh

    def get_shell(self):
        shell = Host._shell_cache.get(self.addr, None)
        if shell is None:
            client = self.get()
            shell = SSHWrapper(client)
            Host._shell_cache[self.addr] = shell
        return shell

    def cmd(self, c, dryrun=False):
        self.log(c)
        if not self.delay:
            if dryrun or self.dryrun:
                return (self.addr, c)
            ssh = self.get()
            self.get_shell().cmd(c)
            return (self.addr, c)
        else:
            self.delayed_cmds.append(c)
        return (self.addr, c)

    def delayed_cmds_execute(self):
        if len(self.delayed_cmds) == 0:
            return None
        self.delay = False
        ssh = self.get()
        cmds = ';'.join(self.delayed_cmds)
        out = ssh.exec_command(cmds)[1].read()
        self.delayed_cmds = []
        return out

    def cmd_async(self, c, dryrun=False):
        self.log(c)
        if not self.delay:
            if dryrun or self.dryrun:
                return (self.addr, c)
            #ssh = self.get()
            #out = ssh.exec_command(c)
            sh = self.get_shell()
            sh.cmd_async(c)
        else:
            self.delayed_cmds.append(c)
        return (self.addr, c)

    def delayed_async_cmds_execute(self):
        if len(self.delayed_cmds) == 0:
            return None
        self.delay = False
        ssh = self.get()
        cmds = ';'.join(self.delayed_cmds)
        out = ssh.exec_command(cmds)[1]
        self.delayed_cmds = []
        return out

    def log(self, c):
        addr = T.colored(self.sshaddr, "magenta")
        c = T.colored(c, "grey", attrs=["bold"])
        print "%s: %s" % (addr, c)

    def get_10g_dev(self):
        return config['DEFAULT_DEV']

    def mkdir(self, dir):
        self.cmd("mkdir -p %s" % dir)

    def rmrf(self, dir):
        print T.colored("removing %s" % dir, "red", attrs=["bold"])
        if dir == "/tmp" or dir == "~" or dir == "/":
            # useless
            return
        self.cmd("rm -rf %s" % dir)

    def rmmod(self, mod=config['RL_MODULE_NAME']):
        self.cmd("rmmod %s" % mod)

    def insmod(self, mod=config['RL_MODULE'], rmmod=True, rate=5000, nrls=1):
        dev = self.get_10g_dev()
        params="dev=%s ntestrls=%s rate=%s" % (dev, nrls, rate)
        cmd = "insmod %s %s" % (mod, params)
        if rmmod:
            cmd = "rmmod %s; " % mod + cmd
        self.cmd(cmd)

    def disable_ipv6(self):
        dev = self.get_10g_dev()
        self.cmd("sysctl -w net.ipv6.conf.%s.disable_ipv6=1;" % dev)

    def insmod_qfq(self):
        self.cmd("rmmod sch_qfq; insmod %s" % config['QFQ_PATH'])
        self.disable_ipv6()
        return

    def remove_qdiscs(self):
        iface = self.get_10g_dev()
        self.cmd("tc qdisc del dev %s root" % iface)

    def add_htb_qdisc(self, rate='5Gbit', mtu=1500):
        iface = self.get_10g_dev()
        self.remove_qdiscs()
        self.rmmod()
        c  = "tc qdisc add dev %s root handle 1: htb default 1;" % iface
        c += "tc class add dev %s classid 1:1 parent 1: " % iface
        c += "htb rate %s mtu %s burst 15k;" % (rate, mtu)
        self.cmd(c)

    def add_htb_hash(self, num_hash_bits=4):
        num_hash_bits = min(8, num_hash_bits)
        num_hash = 1 << num_hash_bits
        self.num_hash = num_hash
        self.hash_mask = hex((1 << num_hash_bits) - 1)
        dev = self.get_10g_dev()
        c  = "tc filter add dev %s parent 1: prio 1 protocol all u32; " % dev
        c += "tc filter add dev %s parent 1: prio 1 handle 2: protocol all u32 divisor %s; " % (dev, num_hash)
        c += "tc filter add dev %s protocol all parent 1: prio 1 u32 ht 800::  match ip protocol 0 0 hashkey mask %s at 20  link 2:; " % (dev, self.hash_mask)
        self.cmd(c)

    def add_one_htb_class(self, rate='5Gbit', ceil='5Gbit', port=1000, klass=1):
        dev = self.get_10g_dev()
        c  = "tc class add dev %s classid 1:%d parent 1: htb rate %s ceil %s; " % (dev, klass, rate, ceil)
        c += "tc filter add dev %s protocol all parent 1: prio 1 u32 ht 2:%d: match ip dport %d %d flowid 1:%d" % (dev, hash, port, self.hash_mask, klass)
        self.cmd(c)

    def add_n_htb_class(self, rate='5Gbit', ceil='5Gbit', start_port=1000, num_class=8):
        num_hash = self.num_hash
        dev = self.get_10g_dev()
        c  = "for klass in `seq %s %s`; do " % (start_port, start_port + num_class)
        c += "  hexclass=`perl -e \"printf('%%x', $klass %% %s)\"`; " % (num_hash)
        c += "  tc filter add dev %s protocol all parent 1: prio 1 u32 ht 2:$hexclass: match ip dport $klass %s flowid 1:%s; " % (dev, self.hash_mask, "$klass")
        c += "  tc class add dev %s classid 1:%s parent 1: htb rate %s ceil %s; " % (dev, "$klass", rate, ceil)
        c += "done;"
        self.cmd(c)

    def htb_class_filter_output(self, dir):
        dev = self.get_10g_dev()
        c  = "tc -s class show dev %s > %s/htb-class.txt" % (dev, dir)
        self.cmd(c)
        c  = "tc -s filter show dev %s > %s/htb-filter.txt" % (dev, dir)
        self.cmd(c)

    def set_mtu(self, mtu=1500):
        iface = self.get_10g_dev()
        c = "ifconfig %s mtu %s" % (iface, mtu)
        self.cmd(c)

    def add_tbf_qdisc(self, rate='5Gbit'):
        iface = self.get_10g_dev()
        self.remove_qdiscs()
        self.rmmod()
        c  = "tc qdisc add dev %s root handle 1: tbf limit 150000 rate %s burst 3000" % (iface, rate)
        self.cmd(c)

    def ifdown(self):
        self.cmd("ifconfig %s down" % self.get_10g_dev())
    def ifup(self):
        self.cmd("ifconfig %s up; sleep 5" % self.get_10g_dev())

    def qfq_stats(self, dir):
        iface = self.get_10g_dev()
        c = "%s -s class show dev %s > %s/qfq-stats.txt" % (config['TC'], iface, dir)
        self.cmd(c)

    def add_qfq_qdisc(self, rate='5000', mtu=1500, nclass=8, startport=1000):
        iface = self.get_10g_dev()
        self.remove_qdiscs()
        self.rmmod()
        self.ifdown()
        c  = "tc qdisc add dev %s root handle 1: qfq;" % iface
        self.cmd(c)
        c = "for klass in {%d..%d}; do " % (startport, startport+nclass-1)
        c += "  tc class add dev %s parent 1: classid 1:$klass qfq weight %s maxpkt 2048; " % (iface, rate)
        c += "  tc filter add dev %s parent 1: protocol all prio 1 u32 match ip dport $klass 0xffff flowid 1:$klass; " % (iface)
        c += "done;"
        """
        for klass in xrange((1 << bits) +1):
            classid = klass + 1
            c += "tc class add dev %s parent 1: classid 1:%d qfq weight %s maxpkt 2048; " % (iface, classid, rate)
            c += "tc filter add dev %s parent 1: protocol all prio 1 u32 match ip sport %d %s flowid 1:%d; " % (iface, klass, mask, classid)
            if klass % 50 == 0:
                self.cmd(c)
                c = ''
        """
        self.cmd(c)
        c = ''
        # Default class
        c += "tc class add dev %s parent 1: classid 1:1 qfq weight %s maxpkt 2048; " % (iface, rate)
        c += "tc filter add dev %s parent 1: protocol all prio 2 u32 match u32 0 0 flowid 1:1; " % iface
        self.cmd(c)
        self.ifup()
        self.disable_tso_gso()

    def disable_tso_gso(self):
        # Disable tso/gso
        iface = self.get_10g_dev()
        c = "ethtool -K %s gso off; ethtool -K %s tso off" % (iface, iface)
        self.cmd(c)

    def qfq_add_root(self, rate_default=100):
        iface = self.get_10g_dev()
        self.remove_qdiscs()
        self.ifdown()
        c = "tc qdisc add dev %s root handle 1: qfq;" % iface
        self.cmd(c)
        self.disable_tso_gso()
        c += "tc class add dev %s parent 1: classid 1:1 qfq weight %s maxpkt 2048; " % (iface, rate_default)
        c += "tc filter add dev %s parent 1: protocol all prio 2 u32 match u32 0 0 flowid 1:1; " % iface
        self.cmd(c)
        self.ifup()

    def qfq_add_class(self, rate, dport):
        dev = self.get_10g_dev()
        c = "tc class add dev %s parent 1: classid 1:%d qfq weight %s maxpkt 2048; " % (dev, dport, rate)
        self.cmd(c)
        c = "tc filter add dev %s parent 1: protocol all prio 1 u32 match ip dport %d 0xffff flowid 1:%d; " % (dev, dport, dport)
        self.cmd(c)

    def killall(self, extra=""):
        for p in self.procs:
            try:
                p.kill()
            except:
                pass
        self.cmd("killall -9 iperf top bwm-ng netperf netserver ethstats %s" % extra)

    def configure_tx_interrupt_affinity(self):
        dev = self.get_10g_dev()
        c = "n=`grep '%s-tx' /proc/interrupts | awk -F ':' '{print $1}' | tr -d '\\n '`; " % dev
        c += " echo 0 > /proc/irq/$n/smp_affinity; "
        self.cmd(c)

    # starting common apps
    def start_netserver(self):
        self.cmd_async("%s/netserver" % config['NETPERF_DIR'])

    def start_iperfserver(self):
        self.cmd_async("iperf -s")

    def start_netperf(self, args, outfile):
        self.cmd_async("%s/netperf %s 2>&1 > %s" % (config['NETPERF_DIR'], args, outfile))

    def start_n_netperfs(self, n, args, dir, outfile_prefix, pin=False):
        cmd = "for i in `seq 1 %s`; do (" % n
        if pin:
            cmd += "taskset -c $((i %% %d)) " % 24
        cmd += " %s/netperf -s 10 %s 2>&1" % (config['NETPERF_DIR'], args)
        cmd += " > %s/%s-$i.txt &);" % (dir, outfile_prefix)
        cmd += " done;"
        self.cmd(cmd)
        return

    def start_n_iperfs(self, n, args, dir):
        batchsize = 100
        times = n/batchsize
        while times:
            cmd = "iperf %s -P %s > %s/iperf-%d.txt" % (args, batchsize, dir, times)
            times -= 1
            n -= batchsize
            self.cmd_async(cmd)
        cmd = "iperf %s -P %s > %s/iperf.txt " % (args, n, dir)
        self.cmd_async(cmd)
        return

    def start_n_udp(self, nclass, nprogs, dest, startport, rate=10000, burst=8850, dir=None):
        # Start nprogs udp traffic sources, nclass per each program,
        # starting with @startport.  I assume each destination port is
        # one class.
        self.cmd_async("unlimit -n 1024000")
        while nprogs:
            nprogs -= 1
            outfile = '%s/udp-%d.txt' % (dir, nprogs)
            if dir is None:
                outfile = '/dev/null'
            cmd = "taskset -c %s %s %s %s %s %s %s > %s 2>&1" % (2, config['UDP'],
                    dest, startport, nclass, rate, burst, outfile)
            self.cmd_async(cmd)
        return

    # Monitoring scripts
    def start_cpu_monitor(self, dir="/tmp"):
        dir = os.path.abspath(dir)
        path = os.path.join(dir, "cpu.txt")
        self.cmd("mkdir -p %s" % dir)
        cmd = "(top -b -p1 -d1 | grep --line-buffered \"^Cpu\") > %s" % path
        return self.cmd_async(cmd)

    def start_bw_monitor(self, dir="/tmp", interval_sec=2):
        dir = os.path.abspath(dir)
        path = os.path.join(dir, "net.txt")
        self.cmd("mkdir -p %s" % dir)
        #cmd = "bwm-ng -t %s -o csv -u bits -T rate -C ',' > %s" % (interval_sec * 1000, path)
        cmd = "ethstats -n1 > %s" % (path)
        return self.cmd_async(cmd)

    def start_perf_monitor(self, dir="/tmp", time=30):
        dir = os.path.abspath(dir)
        path = os.path.join(dir, "perf.txt")
        events = [
            "instructions",
            "cache-misses",
            "branch-instructions",
            "branch-misses",
            "L1-dcache-loads",
            "L1-dcache-load-misses",
            "L1-dcache-stores",
            "L1-dcache-store-misses",
            "L1-dcache-prefetches",
            "L1-dcache-prefetch-misses",
            "L1-icache-loads",
            "L1-icache-load-misses",
            ]
        # This command will use debug counters, so you can't run it when
        # running oprofile
        events = ','.join(events)
        cmd = "(perf stat -e %s -a sleep %d) > %s 2>&1" % (events, time, path)
        return self.cmd_async(cmd)

    def start_qfq_monitor(self, dir):
        cmd = "python %s -i %s > %s/class-stats.txt"
        cmd = cmd % (config['CLASS_RATE'], self.get_10g_dev(), dir)
        self.cmd_async(cmd)

    def start_mpstat(self, dir):
        cmd = "mpstat 1 > %s/mpstat.txt" % dir
        self.cmd_async(cmd)

        cmd = "mpstat 1 -A > %s/mpstat-all.txt" % dir
        self.cmd_async(cmd)

    def stop_mpstat(self):
        self.cmd("killall -9 mpstat")

    def stop_qfq_monitor(self):
        cmd = "pgrep -f class-rate.py | xargs kill -9"
        self.cmd_async(cmd)

    def start_monitors(self, dir='/tmp', interval=1e8):
        return [self.start_cpu_monitor(dir),
                self.start_bw_monitor(dir)]

    def copy_local(self, src_dir="/tmp", exptid=None):
        """Copy remote experiment output to a local directory for analysis"""
        if src_dir == "/tmp":
            return
        if exptid is None:
            print "Please supply experiment id"
            return

        # First compress output
        self.cmd("tar czf /tmp/%s.tar.gz %s --transform='s|tmp/||'" % (exptid, src_dir))
        opts = "-o StrictHostKeyChecking=no"
        c = "scp %s -r %s:/tmp/%s.tar.gz ." % (opts, self.hostname(), exptid)
        print "Copying experiment output"
        local_cmd(c)

    def hostname(self):
        try:
            return socket.gethostbyaddr(self.addr)[0]
        except:
            return self.addr
