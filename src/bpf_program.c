/* src/bpf_program.c
 *
 * eBPF TC egress classifier for Quake Live packet size capture.
 * Filters outbound UDP packets on configurable port range,
 * records (dest_ip, packet_size) into a BPF hash map.
 *
 * Loaded by BCC at runtime — port range injected via cflags (-DPORT_MIN, -DPORT_MAX).
 */

#include <uapi/linux/bpf.h>
#include <uapi/linux/if_ether.h>
#include <uapi/linux/ip.h>
#include <uapi/linux/udp.h>
#include <uapi/linux/pkt_cls.h>

/* PORT_MIN and PORT_MAX are injected by Python via BCC cflags:
 *   -DPORT_MIN=27960 -DPORT_MAX=27963
 */

struct packet_key {
    u32 dest_ip;
    u32 size_bucket;  /* UDP payload size, bucketed in userspace */
};

/* Map: (dest_ip, udp_payload_size) -> packet_count */
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
    if (ip->protocol != IPPROTO_UDP)
        return TC_ACT_OK;

    /* Parse UDP header (account for variable IP header length) */
    if (ip->ihl < 5)
        return TC_ACT_OK;
    struct udphdr *udp = (void *)ip + (ip->ihl * 4);
    if ((void *)(udp + 1) > data_end)
        return TC_ACT_OK;

    u16 sport = bpf_ntohs(udp->source);
    if (sport < PORT_MIN || sport > PORT_MAX)
        return TC_ACT_OK;

    /* UDP payload size = total UDP length - 8 byte header */
    u16 udp_len = bpf_ntohs(udp->len);
    if (udp_len < 8)
        return TC_ACT_OK;
    u16 udp_payload = udp_len - 8;

    struct packet_key key = {};
    key.dest_ip = ip->daddr;
    key.size_bucket = udp_payload;

    u64 *count = packet_counts.lookup_or_try_init(&key, &(u64){0});
    if (count) {
        __sync_fetch_and_add(count, 1);
    }

    return TC_ACT_OK;  /* Don't interfere with traffic */
}
