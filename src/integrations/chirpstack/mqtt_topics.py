from dataclasses import dataclass


class ChirpStackTopicParseError(ValueError):
    pass


@dataclass(slots=True, frozen=True)
class ChirpStackTopicInfo:
    application_id: str
    dev_eui: str
    event_type: str


@dataclass(slots=True, frozen=True)
class ChirpStackDownlinkTopicInfo:
    application_id: str
    dev_eui: str


def parse_chirpstack_event_topic(topic: str) -> ChirpStackTopicInfo:
    parts = topic.split("/")
    if len(parts) != 6:
        raise ChirpStackTopicParseError("Invalid ChirpStack topic format")

    if parts[0] != "application" or parts[2] != "device" or parts[4] != "event":
        raise ChirpStackTopicParseError("Invalid ChirpStack topic segments")

    application_id = parts[1].strip()
    dev_eui = "".join(parts[3].split()).lower()
    event_type = parts[5].strip().lower()

    if not application_id or not dev_eui or not event_type:
        raise ChirpStackTopicParseError("Incomplete ChirpStack topic")

    return ChirpStackTopicInfo(
        application_id=application_id,
        dev_eui=dev_eui,
        event_type=event_type,
    )


def parse_chirpstack_downlink_topic(topic: str) -> ChirpStackDownlinkTopicInfo:
    parts = topic.split("/")
    if len(parts) != 6:
        raise ChirpStackTopicParseError("Invalid ChirpStack downlink topic format")

    if parts[0] != "application" or parts[2] != "device" or parts[4] != "command":
        raise ChirpStackTopicParseError("Invalid ChirpStack downlink topic segments")

    if parts[5] != "down":
        raise ChirpStackTopicParseError("Unsupported ChirpStack downlink topic suffix")

    application_id = parts[1].strip()
    dev_eui = "".join(parts[3].split()).lower()
    if not application_id or not dev_eui:
        raise ChirpStackTopicParseError("Incomplete ChirpStack downlink topic")

    return ChirpStackDownlinkTopicInfo(
        application_id=application_id,
        dev_eui=dev_eui,
    )


def is_chirpstack_downlink_topic(topic: str) -> bool:
    try:
        parse_chirpstack_downlink_topic(topic)
    except ChirpStackTopicParseError:
        return False
    return True
