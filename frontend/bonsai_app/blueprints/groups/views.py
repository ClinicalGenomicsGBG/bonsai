"""Declaration of views for groups"""

import json
import logging
from typing import Any
from urllib.parse import urlparse

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from jsonpath2.path import Path as jsonPath
from requests.exceptions import HTTPError

from ...bonsai import (
    TokenObject,
    create_group,
    delete_group,
    get_group_by_id,
    get_groups,
    get_samples,
    get_samples_in_group,
    get_valid_group_columns,
    update_group,
    update_sample_qc_classification,
)
from ...models import BadSampleQualityAction, PhenotypeType, QualityControlResult

from ...hci import get_hci_samples

LOG = logging.getLogger(__name__)

groups_bp = Blueprint(
    "groups",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/groups/static",
)


def external_to_samples(response):
    samples = []

    def first(metadata, key):
        values = metadata.get(key, [])
        return values[0] if values else ""

    for result in response.get("results", []):
        metadata = result.get("metadata", {})

        profile_raw = first(metadata, "pipelineAnalysis_profile")
        try:
            profile = json.loads(profile_raw) if profile_raw else []
        except (json.JSONDecodeError, TypeError):
            profile = []

        samples.append({
            "sample_id": first(metadata, "rootSample_name"),
            "sample_name": first(metadata, "rootSample_name"),
            "lims_id": first(metadata, "rootLims_id"),
            "assay": first(metadata, "pipelineAssay"),
            "release_life_cycle": first(
                metadata, "pipelineRelease_life_cycle"
            ),
            "sequencing_run": first(metadata, "sequencingRun_id"),

            "species_prediction": {
                "scientific_name": ""
            },
            "qc_status": {
                "status": ""
            },

            "profile": profile,
            "comments": [],
            "tags": [],

            "mlst": first(
                metadata,
                "typing_result_resultSequence_type"
            ),
            "stx": "",
            "oh_type": "",

            "created_at": first(metadata, "HCI_doc_version"),
        })

    return {
        "data": samples,
        "records_total": response.get("hitCount", len(samples)),
    }


@groups_bp.route("/groups")
@login_required
def groups() -> str:
    """Generate page that displays groups and all samples.

    :return: generated HTML page
    :rtype: str
    """
    all_samples = {"data": []}

    search_term = request.args.get("searchterm", "").strip()
    if search_term:
        #all_samples = search_remote_samples(search_term)
        resp = get_hci_samples(search_term)
        all_samples = external_to_samples(resp)

    if False:
        return str(resp)
    #formatted = reformat_hci_resp(resp)

    # if not valid token
    if current_user.get_id() is None:
        LOG.info(
            "User not logged in: %s %s", current_user.first_name, current_user.last_name
        )
        return redirect(url_for("public.index"))

    token = TokenObject(**current_user.get_id())
    #all_samples = get_samples(token, limit=0, skip=0)

    bad_qc_actions = [member.value for member in BadSampleQualityAction]

    # get default columns from api
    default_columns: list[dict[str, str | bool | jsonPath | None]] = []
    for col in get_valid_group_columns(token_obj=token):
        if col["hidden"]:
            continue
        # get path
        col["path"] = jsonPath.parse_str(col["path"])
        default_columns.append(col)

    # generate table data
    table_data: list[dict[str, Any]] = []
    for sample in all_samples["data"]:
        row: list[dict[str, Any]] = []
        for col in default_columns:
            # get sample data from json path
            raw_data: list[str] = [
                mat.current_value for mat in col["path"].match(sample)
            ]
            data = raw_data[0] if len(raw_data) > 0 else ""
            row.append(
                {
                    "id": col["id"],
                    "label": col["label"],
                    "type": col["type"],
                    "data": data,
                }
            )
        if len(row) > 0:
            table_data.append(row)

    return render_template(
        "groups.html",
        title="Groups",
        table_data=table_data,
        basket_samples=all_samples["data"],
        token=current_user.get_id().get("token"),
        bad_qc_actions=bad_qc_actions,
    )


@groups_bp.route("/groups/edit", methods=["GET", "POST"])
@groups_bp.route("/groups/edit/<group_id>", methods=["GET", "POST"])
@login_required
def edit_groups(group_id: str | None = None):
    """Generate edit groups view

    :param group_id: Group id, defaults to None
    :type group_id: str, optional
    :return: generated HTML page
    :rtype: str
    """
    # if not valid token or if user is not admin
    if current_user.get_id() is None or not current_user.is_admin:
        return redirect(url_for("public.index"))

    token = TokenObject(**current_user.get_id())
    all_groups = get_groups(token)

    # remove group from database
    if request.method == "POST":
        # if a group should be removed
        if "input-remove-group" in request.form:
            try:
                delete_group(token, group_id=request.form.get("input-remove-group"))
                flash("Group updated", "success")
            except HTTPError as err:
                flash(f"An error occured when updating group, {err}", "danger")
            return redirect(url_for("groups.edit_groups"))
        elif "input-update-group" in request.form:
            updated_data = json.loads(request.form.get("input-update-group"))
            try:
                update_group(token, group_id=group_id, data=updated_data)
                flash("Group updated", "success")
                return redirect(url_for("groups.edit_groups", group_id=group_id))
            except HTTPError as err:
                flash(f"An error occured when updating group, {err}", "danger")
        elif "input-create-group" in request.form:
            input_data = json.loads(request.form.get("input-create-group", {}))
            try:
                group_id = input_data["group_id"]
                create_group(token, data=input_data)
                flash("Group updated", "success")
                return redirect(url_for("groups.edit_groups", group_id=group_id))
            except HTTPError as err:
                flash(f"An error occured when updating group, {err}", "danger")

    # get valid phenotypes
    valid_phenotypes = {
        entry.name.lower().capitalize().replace("_", " "): entry.value
        for entry in PhenotypeType.__members__.values()
    }

    # get valid columns and set used cols as checked
    valid_cols = get_valid_group_columns(group_id=group_id, token_obj=token)
    all_group_ids = [group["group_id"] for group in all_groups]
    if group_id is not None and group_id in all_group_ids:
        selected_group = next(
            iter(group for group in all_groups if group["group_id"] == group_id)
        )
        cols_in_group = [gr["path"] for gr in selected_group["table_columns"]]
    else:
        cols_in_group = []
    # annotate if column previously have been selected
    for column in valid_cols:
        column["selected"] = column["path"] in cols_in_group
    return render_template(
        "edit_groups.html",
        title="Groups",
        selected_group=group_id,
        groups=all_groups,
        valid_columns=valid_cols,
        valid_phenotypes=valid_phenotypes,
    )


@groups_bp.route("/groups/<group_id>")
@login_required
def group(group_id: str) -> str:
    """Group view.

    :param group_id: Group id
    :type group_id: str
    :return: html page
    :rtype: str
    """
    # check if qc metrics should be displayed
    display_qc: bool = request.args.get(
        "qc", False, type=lambda val: val.lower() == "true"
    )

    # query API for sample info
    token = TokenObject(**current_user.get_id())
    try:
        samples_info = get_samples_in_group(
            token,
            group_id=group_id,
            prediction_result=not display_qc,
            qc_metrics=display_qc,
        )
        # get column definition to use
        group_info = get_group_by_id(token, group_id=group_id)
    except HTTPError as error:
        # throw proper error page
        abort(error.response.status_code)

    # Pre-select samples in sample table:
    selected_samples = request.args.getlist("samples")

    bad_qc_actions = [member.value for member in BadSampleQualityAction]

    # get columns from api
    group_columns: list[dict[str, Any]] = []
    for col in (
        get_valid_group_columns(token_obj=token, qc=True) if display_qc else group_info["table_columns"]
    ):
        if col["hidden"]:
            continue
        # get path
        upd_col = col.copy()
        upd_col["path"] = jsonPath.parse_str(upd_col["path"])
        group_columns.append(upd_col)

    # generate table data
    table_data = []
    for sample in samples_info["data"]:
        row = []
        for col in group_columns:
            # get sample data from json path
            data = [m.current_value for m in col["path"].match(sample)]
            data = data[0] if len(data) > 0 else ""
            row.append(
                {
                    "id": col["id"],
                    "label": col["label"],
                    "type": col["type"],
                    "data": data,
                }
            )
        if len(row) > 0:
            table_data.append(row)

    # indicate view in title, used for testing
    title = f"Group - {group_id}"
    if display_qc:
        title += " - QC results"
    return render_template(
        "group.html",
        title=title,
        group_id=group_id,
        group_name=group_info["display_name"],
        bad_qc_actions=bad_qc_actions,
        selected_samples=selected_samples,
        group_desc=group_info["description"],
        table_data=table_data,
        basket_samples=samples_info["data"],
        table_definition=group_info["table_columns"],
        modified=group_info["modified_at"],
        display_qc=display_qc,
        token=current_user.get_id().get("token"),
    )


@groups_bp.route("/groups/qc_status", methods=["POST"])
@login_required
def update_qc_classification():
    """Update the quality control report of one or more samples.

    Redirects back to groups.groups and preserves table selection
    """

    selected_samples = request.form.getlist("qc-selected-samples")

    LOG.debug("Processing request to set QC for %s", selected_samples)

    if not selected_samples:
        LOG.warning("Received request to set QC but no selected samples")
        flash(
            "No samples selected for QC status update. Please choose at least one sample.",
            "warning",
        )

    token = TokenObject(**current_user.get_id())

    # build data to store in db
    result = request.form.get("qc-validation", None)
    if result == QualityControlResult.PASSED.value:
        action = None
        comment = ""
    elif result == QualityControlResult.FAILED.value:
        comment = request.form.get("qc-comment", "")
        action = request.form.get("qc-action", "")
    else:
        raise ValueError(f"Unknown value of qc classification, {result}")

    for sample_id in selected_samples:
        try:
            update_sample_qc_classification(
                token,
                sample_id=sample_id,
                status=result,
                action=action,
                comment=comment,
            )
        except Exception as error:
            LOG.exception(
                "Encountered error when updating QC status for sample %s:", sample_id
            )
            flash(str(error), "danger")

    # return redirect(url_for("groups.groups", samples=selected_samples))
    # add sample ids as params to referrer url
    url = urlparse(request.referrer)
    sample_id_param = "&".join([f"samples={sid}" for sid in selected_samples])
    upd_url = url._replace(query=sample_id_param).geturl()
    return redirect(upd_url)
