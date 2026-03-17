/* src/bpf_program.c
 *
 * eBPF TC egress classifier for Quake Live packet size capture.
 * Runs on the loopback interface (lo) — all QL→client traffic is routed
 * through loopback due to SNAT (99k LAN rate setup).
 *
 * Filters outbound UDP packets where source port is in the configured QL
 * server port range, records (dest_port, packet_size) into a BPF hash map.
 * dest_port is the client's qport — unique per session, used for player correlation.
 *
 * Loaded by BCC at runtime — port range injected via cflags (-DPORT_MIN, -DPORT_MAX).
 */

#include <uapi/linux/bpf.h>
#include <uapi/linux/if_ether.h>
#include <uapi/linux/ip.h>
#include <uapi/linux/udp.h>
#include <uapi/linux/pkt_cls.h>
#include <uapi/linux/in.h>

/* PORT_MIN and PORT_MAX are injected by Python via BCC cflags:
 *   -DPORT_MIN=27962 -DPORT_MAX=27962
 */

struct packet_key {
    u32 dest_port;   /* client qport — unique per session */
    u32 size_bucket; /* UDP payload size, bucketed in userspace */
};

/* Map: (dest_port, udp_payload_size) -> packet_count */
BPF_HASH(packet_counts, struct packet_key, u64, 16384);

int classify(struct __sk_buff *skb) {
    void *data = (void *)(long)skb->data;
    void *data_end = (void *)(long)skb->data_end;

    /* Parse Ethernet header */
    struct ethhdr *eth = data;
    if ((void *)(eth + 1) > data_end)
        return TC_ACT_OK;
    if (eth->h_proto != __constant_htons(ETH_P_IP))
        return TC_ACT_OK;

    /* Parse IP header */
    struct iphdr *ip = (void *)(eth + 1);
    if ((void *)(ip + 1) > data_end)
        return TC_ACT_OK;
    if (ip->ihl < 5)
        return TC_ACT_OK;
    if (ip->protocol != IPPROTO_UDP)
        return TC_ACT_OK;

    /* Parse UDP header */
    struct udphdr *udp = (void *)ip + (ip->ihl * 4);
    if ((void *)(udp + 1) > data_end)
        return TC_ACT_OK;

    /* Filter: source port must be our QL server port */
    u16 sport = bpf_ntohs(udp->source);
    if (sport < PORT_MIN || sport > PORT_MAX)
        return TC_ACT_OK;

    /* UDP payload size = total UDP length - 8 byte header */
    u16 udp_len = bpf_ntohs(udp->len);
    if (udp_len < 8)
        return TC_ACT_OK;
    u16 udp_payload = udp_len - 8;

    /* Key: client qport (dest) + payload size */
    struct packet_key key = {};
    key.dest_port = bpf_ntohs(udp->dest);
    key.size_bucket = udp_payload;

    u64 *count = packet_counts.lookup_or_try_init(&key, &(u64){0});
    if (count) {
        __sync_fetch_and_add(count, 1);
    }

    return TC_ACT_OK;
}
