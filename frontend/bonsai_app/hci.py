from NGPIris import HCIHandler


def get_hci_samples(search_term):
    h = HCIHandler("/home/worker/app/bonsai_app/hci_1.json")
    h.request_token()
    resp = h.raw_query(
        {
            "indexName" : "bonsai_index_1",
            "queryString" : f"{search_term}",
            "itemsToReturn" : 1000
        }
    )
    return resp
