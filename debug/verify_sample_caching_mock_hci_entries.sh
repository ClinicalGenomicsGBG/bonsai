#!/usr/bin/env bash
set -euo pipefail


# -------------------------------------------------------

# argument handling:
# - source: https://keestalkstech.com/named-arguments-in-a-bash-script/
# - modified: johancz

declare sample_id="" print_hci_entry_summary=false check_hcp=false hcp_key="" overview_all_samples=false
# declare -ar allowed_arguments=(service_name tag namespace env print_hci_entry_summary)
declare -ar allowed_arguments=(sample_id print_hci_entry_summary check_hcp hcp_key overview_all_samples)
declare -ar required_arguments=(sample_id)
declare -A seen=()

usage() {
    local script_name="${0##*/}"
    printf 'usage: %s --sample-id string [options]\n' "$script_name"

    cat <<EOF

  -s, --sample-id string      The sample_id for the Sample to verify.
  --check-hcp bool            Check whether the object was actually uploaded to the hcp
                              (true | false, default: false)
  --hcp-key string            The HCP object key to check
                              (required when --check-hcp is true)
  --print-hci-entry-summary bool
                              Print the mock HCI object's summary.
                              (true | false, default: false)
  --overview-all-samples bool Print an overview of all samples.
                              (true | false, default: false)
  -h, --help                  show this help

EOF
}

die() {
    printf "Script failed: %s\n" "$1" >&2
    exit 1
}

is_allowed_argument() {
    local allowed
    for allowed in "${allowed_arguments[@]}"; do
        [[ $1 == "$allowed" ]] && return 0
    done
    return 1
}

while (( $# > 0 )); do
    case $1 in
        -h|--help) usage; exit 0 ;;
        --*) ;;
        -s) set -- --sample-id "${@:2}" ;;
        -*) die "Unknown option: $1" ;;
        *)  die "Unexpected positional argument: $1" ;;
    esac

    flag=${1%%=*}
    name=${flag#--}; name=${name//-/_}
    is_allowed_argument "$name" || die "Unknown parameter: $flag"
    # [[ -z ${!name} ]] || die "Duplicate parameter: $flag"
    [[ -z ${seen[$name]-} ]] || die "Duplicate parameter: $flag"
    seen[$name]=1

    if [[ $1 == *=* ]]; then
        value=${1#*=}; shift
    else
        (( $# >= 2 )) && [[ $2 != -* ]] || die "Missing value for $flag"
        value=$2; shift 2
    fi
    printf -v "$name" "%s" "$value"
done

missing=()
for arg in "${required_arguments[@]}"; do
    [[ -n ${!arg} ]] || missing+=("--${arg//_/-}")
done
if (( ${#missing[@]} )); then
    usage >&2
    die "Missing parameter(s): ${missing[*]}"
fi


run_additional_validation() {
    [[ $sample_id =~ ^[A-Za-z0-9_.-]+$ ]] || die "Invalid --sample-id '$sample_id' (allowed: letters, digits, _ . -)"
    [[ $print_hci_entry_summary =~ ^(true|false)$ ]] || die "Invalid --print-hci-entry-summary '$print_hci_entry_summary' (expected true or false)"
    [[ $check_hcp =~ ^(true|false)$ ]] || die "Invalid --check-hcp '$check_hcp' (expected true or false)"
    if [[ $check_hcp == true && -z $hcp_key ]]; then
        die "--hcp-key is required when --check-hcp is true"
    fi

    [[ $overview_all_samples =~ ^(true|false)$ ]] || die "Invalid --overview-all-samples '$overview_all_samples' (expected true or false)"
}

run_additional_validation

printf "print_hci_entry_summary: %s\n" "$print_hci_entry_summary"


# -------------------------------------------------------


PC='podman-compose --in-pod=false --env-file development.env -f docker-compose.yml -f compose.yml'

# SAMPLE_ID="${1:-test_1791383548-20261007-1632}"
SAMPLE_ID="$sample_id"
echo "Verifying sample: '$SAMPLE_ID'..."

printf "\n===== 1. Sample document in 'bonsai' DB: ========================\n"
$PC exec -T mongodb mongo bonsai --quiet --eval "
db.sample.find(
  {sample_id: '$SAMPLE_ID'},
  {sample_id: 1, created_at: 1, 'pipeline.assay': 1}
).forEach(printjson)"

printf "\n===== 2. (Sample) cache entry in 'bonsai' DB: ===================\n"
$PC exec -T mongodb mongo bonsai --quiet --eval "printjson(db.cached_sample.findOne({sample_id: '$SAMPLE_ID'}, {_id: 0}))"

printf "\n===== 3a. Mock HCI entry (without summary) in 'bonsai' D:B: =======\n"
$PC exec -T mongodb mongo hci_mock --quiet --eval "printjson(db.sample.findOne({sample_id: '$SAMPLE_ID'}, {_id: 0, summary: 0}))"
HCP_KEY="$($PC exec -T mongodb mongo hci_mock --quiet --eval "var d = db.sample.findOne({sample_id: '$SAMPLE_ID'}); print(d ? d.hcp_key : '')")"
echo "$HCP_KEY"

if [[ "$print_hci_entry_summary" = true ]]; then
  printf "\n===== 3b. Mock HCI entry (with summary) in 'bonsai' DB: ==========\n"
  $PC exec -T mongodb mongo hci_mock --quiet --eval "printjson(db.sample.findOne({sample_id: '$SAMPLE_ID'}).summary)"
fi

printf "\n===== 4. Check that the (sample) mock entry point to the actual sample document =====\n"
$PC exec -T mongodb mongo --quiet --eval "
var m = db.getSiblingDB('hci_mock').sample.findOne({sample_id: '$SAMPLE_ID'});
var s = db.getSiblingDB('bonsai').sample.findOne({_id: ObjectId(m.summary.id)});
print('mock entry points to an existing sample document:', s !== null);"

printf "\n===== 5. Check indices =====\n"
$PC exec -T mongodb mongo bonsai --quiet --eval "printjson(db.cached_sample.getIndexes().map(i => i.name))"
$PC exec -T mongodb mongo hci_mock --quiet --eval "printjson(db.sample.getIndexes().map(i => i.name))"


if [[ "$overview_all_samples" = true ]]; then
  printf "\n===== 6. Overview of all samples. Samples uploaded before this change, or with the HCP upload switched off, are expected to appear in the 'without' lists. =====\n"
  $PC exec -T mongodb mongo --quiet --eval "
  var b = db.getSiblingDB('bonsai'),
      h = db.getSiblingDB('hci_mock');
  var ids = b.sample.distinct('sample_id');
  print(
    'samples:',
    ids.length,
    '| cache entries:',
    b.cached_sample.countDocuments({}),
    '| mock entries:',
    h.sample.countDocuments({})
  );
  print('without cache entry:', tojson(ids.filter(id => !b.cached_sample.findOne({sample_id: id}))));
  print('without mock entry:', tojson(ids.filter(id => !h.sample.findOne({sample_id: id}))));"
fi


# if [[ "$check_hcp" = true && -n "$hcp_key" ]]; then
if [[ "$check_hcp" = true && -n "$HCP_KEY" ]]; then
  printf "\n===== 7. Is the object really in HCP? =====\n"
  $PC exec -T hci_hcp_service python -c "
  from hci_hcp_service.tasks import load_settings, connect
  print(
      'object in HCP:',
      connect(load_settings()).object_exists('$HCP_KEY')
  )"
else
  echo "NOT checking hcp, done!"
fi
