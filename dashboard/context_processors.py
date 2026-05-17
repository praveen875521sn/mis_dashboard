"""
Template context processors — make values available in every template.
"""
from dashboard.models import Centre, ClusterMaster, SAHIDemand


def cluster_counts(request):
    """
    Inject cluster_count + sub_cluster_count into every template.
    'Depend' behavior: if a Cluster is selected in the query string,
    sub_cluster_count narrows to only that cluster's sub clusters.
    """
    cluster = request.GET.get('cluster', '') if hasattr(request, 'GET') else ''

    # Union across Centre + ClusterMaster + SAHIDemand so demand-only
    # clusters (Indore, Goa, Dewas, …) are counted too.
    cluster_set = (
        set(ClusterMaster.objects.exclude(cluster='')
              .values_list('cluster', flat=True))
        | set(Centre.objects.exclude(cluster='').exclude(cluster=None)
                .values_list('cluster', flat=True))
        | set(SAHIDemand.objects.exclude(cluster='')
                .values_list('cluster', flat=True))
    )

    sc_master = ClusterMaster.objects.exclude(sub_cluster='')
    sc_centre = Centre.objects.exclude(sub_cluster='').exclude(sub_cluster=None)
    sc_demand = SAHIDemand.objects.exclude(sub_cluster='')
    if cluster:
        sc_master = sc_master.filter(cluster=cluster)
        sc_centre = sc_centre.filter(cluster=cluster)
        sc_demand = sc_demand.filter(cluster=cluster)
    sub_cluster_set = (
        set(sc_master.values_list('sub_cluster', flat=True))
        | set(sc_centre.values_list('sub_cluster', flat=True))
        | set(sc_demand.values_list('sub_cluster', flat=True))
    )

    # Cluster count narrows to 1 when a cluster is selected (matches Sub Cluster behavior).
    if cluster:
        cluster_count = 1 if cluster in cluster_set else 0
    else:
        cluster_count = len(cluster_set)

    return {
        'nav_cluster_count':     cluster_count,
        'nav_sub_cluster_count': len(sub_cluster_set),
        'nav_cluster_active':    bool(cluster),
    }
