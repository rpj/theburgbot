create table invites (
    passphrase text not null,
    created_at date not null,
    discord_code text,
    redeemed_at date,
    requestor_name text not null,
    requestor_id text not null,
    invite_for text not null
);

create table message_log (
    channel_id text not null,
    channel_name text not null,
    author_id text not null,
    author_name text not null,
    message_id text not null,
    content text not null,
    timestamp date not null
);

create table audit_log (
    event text not null,
    message text,
    timestamp date not null
);

create table cmd_use_log (
    command text not null,
    user_id text not null,
    display_name text not null,
    timestamp date not null
);

create table http_static (
    created date not null,
    updated date,
    pub_id text not null,
    from_user_id text not null,
    from_command text not null,
    rendered text not null,
    template text not null,
    src_obj_json text not null
);