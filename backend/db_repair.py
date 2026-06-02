"""Database schema repair helpers for the admin database page.

Keep these specs in sync with sql/schema.sql whenever the database schema changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pymysql.err import MySQLError

from backend.database import get_db_connection


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    definition: str
    column_type: str
    nullable: bool
    default: str | None
    comment: str = ""
    safe_definition: str | None = None
    placeholder_sql: str | None = None


@dataclass(frozen=True)
class IndexSpec:
    name: str
    sql: str


@dataclass(frozen=True)
class ForeignKeySpec:
    name: str
    table: str
    column: str
    referenced_table: str
    referenced_column: str
    sql: str


@dataclass(frozen=True)
class TableSpec:
    name: str
    create_sql: str
    columns: tuple[ColumnSpec, ...]
    indexes: tuple[IndexSpec, ...]


def _required_text(name: str, size: int, comment: str, placeholder: str = "") -> ColumnSpec:
    return ColumnSpec(
        name=name,
        definition=f"VARCHAR({size}) NOT NULL COMMENT '{comment}'",
        safe_definition=f"VARCHAR({size}) NULL COMMENT '{comment}'",
        column_type=f"varchar({size})",
        nullable=False,
        default=None,
        comment=comment,
        placeholder_sql=f"'{placeholder}'",
    )


def _required_long_text(name: str, comment: str) -> ColumnSpec:
    return ColumnSpec(
        name=name,
        definition=f"TEXT NOT NULL COMMENT '{comment}'",
        safe_definition=f"TEXT NULL COMMENT '{comment}'",
        column_type="text",
        nullable=False,
        default=None,
        comment=comment,
        placeholder_sql="''",
    )


def _required_int(name: str, comment: str, placeholder: int = 0) -> ColumnSpec:
    return ColumnSpec(
        name=name,
        definition=f"INT NOT NULL COMMENT '{comment}'",
        safe_definition=f"INT NULL COMMENT '{comment}'",
        column_type="int",
        nullable=False,
        default=None,
        comment=comment,
        placeholder_sql=str(placeholder),
    )


USERS_COLUMNS = (
    ColumnSpec("id", "INT AUTO_INCREMENT PRIMARY KEY COMMENT '用户 ID'", "int", False, None, "用户 ID"),
    _required_text("username", 32, "昵称/登录用户名", "user"),
    _required_text("password_hash", 255, "PBKDF2 密码哈希", "pbkdf2_placeholder"),
    ColumnSpec("display_name", "VARCHAR(80) DEFAULT NULL COMMENT '姓名'", "varchar(80)", True, None, "姓名"),
    ColumnSpec(
        "role",
        "ENUM('admin', 'user') NOT NULL DEFAULT 'user' COMMENT '用户角色：admin 管理员，user 普通用户'",
        "enum('admin','user')",
        False,
        "user",
        "用户角色：admin 管理员，user 普通用户",
    ),
    ColumnSpec("is_active", "TINYINT(1) NOT NULL DEFAULT 1 COMMENT '账号是否启用'", "tinyint(1)", False, "1", "账号是否启用"),
    ColumnSpec("created_at", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP", "timestamp", False, "CURRENT_TIMESTAMP"),
    ColumnSpec(
        "updated_at",
        "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
        "timestamp",
        False,
        "CURRENT_TIMESTAMP",
    ),
)

PROJECTS_COLUMNS = (
    ColumnSpec("id", "INT AUTO_INCREMENT PRIMARY KEY COMMENT '项目 ID'", "int", False, None, "项目 ID"),
    _required_text("name", 120, "项目名称"),
    _required_text("leader", 80, "负责人"),
    _required_long_text("members", "项目成员，可用逗号分隔或 JSON 字符串"),
    _required_text("category", 60, "分类，例如 科技创新/公益服务/艺术设计"),
    _required_int("year", "项目年份"),
    ColumnSpec("icon", "VARCHAR(255) DEFAULT NULL COMMENT '项目图标图片 URL'", "varchar(255)", True, None, "项目图标图片 URL"),
    _required_long_text("description", "简要介绍/完整简介"),
    ColumnSpec("media", "JSON DEFAULT NULL COMMENT '照片/视频链接数组，JSON 格式'", "json", True, None, "照片/视频链接数组，JSON 格式"),
    ColumnSpec("cas_creativity", "TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否包含 Creativity'", "tinyint(1)", False, "0", "是否包含 Creativity"),
    ColumnSpec("cas_activity", "TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否包含 Activity'", "tinyint(1)", False, "0", "是否包含 Activity"),
    ColumnSpec("cas_service", "TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否包含 Service'", "tinyint(1)", False, "0", "是否包含 Service"),
    ColumnSpec("popularity", "INT NOT NULL DEFAULT 0 COMMENT '热度，用于推荐排序'", "int", False, "0", "热度，用于推荐排序"),
    ColumnSpec("updates", "JSON DEFAULT NULL COMMENT '项目动态数组，JSON 格式'", "json", True, None, "项目动态数组，JSON 格式"),
    ColumnSpec("created_at", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP", "timestamp", False, "CURRENT_TIMESTAMP"),
    ColumnSpec(
        "updated_at",
        "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
        "timestamp",
        False,
        "CURRENT_TIMESTAMP",
    ),
)

PROJECT_CATEGORY_COLUMNS = (
    ColumnSpec("id", "INT AUTO_INCREMENT PRIMARY KEY COMMENT 'CAS 项目分类 ID'", "int", False, None, "CAS 项目分类 ID"),
    _required_text("name", 60, "CAS 项目分类名称"),
    ColumnSpec("sort_order", "INT NOT NULL DEFAULT 0 COMMENT '人工排序权重，数字越小越靠前'", "int", False, "0", "人工排序权重，数字越小越靠前"),
    ColumnSpec("is_active", "TINYINT(1) NOT NULL DEFAULT 1 COMMENT '分类是否启用'", "tinyint(1)", False, "1", "分类是否启用"),
    ColumnSpec("created_at", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP", "timestamp", False, "CURRENT_TIMESTAMP"),
    ColumnSpec(
        "updated_at",
        "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
        "timestamp",
        False,
        "CURRENT_TIMESTAMP",
    ),
)

RESOURCES_COLUMNS = (
    ColumnSpec("id", "INT AUTO_INCREMENT PRIMARY KEY COMMENT '资源 ID'", "int", False, None, "资源 ID"),
    _required_text("title", 160, "资源标题"),
    ColumnSpec("description", "TEXT COMMENT '资源简介'", "text", True, None, "资源简介"),
    _required_int("year", "资源年份"),
    _required_text("category", 40, "普通资源分类值，例如 yearbook/other；活动照片不写入 resources"),
    _required_text("label", 60, "资源分类展示名"),
    ColumnSpec("hot", "INT NOT NULL DEFAULT 0 COMMENT '热度'", "int", False, "0", "热度"),
    ColumnSpec("downloads", "INT NOT NULL DEFAULT 0 COMMENT '下载次数'", "int", False, "0", "下载次数"),
    _required_text("image", 600, "封面图片 URL"),
    _required_text("resource_url", 600, "资源访问或下载 URL"),
    ColumnSpec("created_at", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP", "timestamp", False, "CURRENT_TIMESTAMP"),
    ColumnSpec(
        "updated_at",
        "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
        "timestamp",
        False,
        "CURRENT_TIMESTAMP",
    ),
)

RESOURCE_CATEGORY_COLUMNS = (
    ColumnSpec("id", "INT AUTO_INCREMENT PRIMARY KEY COMMENT '资源分类 ID'", "int", False, None, "资源分类 ID"),
    _required_text("value", 40, "资源分类入口值，例如 yearbook/photos/other；photos 只作为活动照片入口"),
    _required_text("label", 60, "资源分类展示名称"),
    ColumnSpec("sort_order", "INT NOT NULL DEFAULT 0 COMMENT '人工排序权重，数字越小越靠前'", "int", False, "0", "人工排序权重，数字越小越靠前"),
    ColumnSpec("is_active", "TINYINT(1) NOT NULL DEFAULT 1 COMMENT '分类是否启用'", "tinyint(1)", False, "1", "分类是否启用"),
    ColumnSpec("created_at", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP", "timestamp", False, "CURRENT_TIMESTAMP"),
    ColumnSpec(
        "updated_at",
        "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
        "timestamp",
        False,
        "CURRENT_TIMESTAMP",
    ),
)

PHOTO_ACTIVITY_COLUMNS = (
    ColumnSpec("id", "INT AUTO_INCREMENT PRIMARY KEY COMMENT '活动 ID'", "int", False, None, "活动 ID"),
    _required_text("activity", 160, "活动名称"),
    _required_long_text("description", "活动照片简介"),
    _required_int("year", "活动年份"),
    ColumnSpec("hot", "INT NOT NULL DEFAULT 0 COMMENT '活动热度'", "int", False, "0", "活动热度"),
    ColumnSpec("downloads", "INT NOT NULL DEFAULT 0 COMMENT '下载次数'", "int", False, "0", "下载次数"),
    ColumnSpec("sort_order", "INT NOT NULL DEFAULT 0 COMMENT '人工排序权重，数字越小越靠前'", "int", False, "0", "人工排序权重，数字越小越靠前"),
    ColumnSpec("photo_dir", "VARCHAR(600) DEFAULT NULL COMMENT '活动照片目录 URL，指向 public 下的文件夹'", "varchar(600)", True, None, "活动照片目录 URL，指向 public 下的文件夹"),
    ColumnSpec("created_at", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP", "timestamp", False, "CURRENT_TIMESTAMP"),
    ColumnSpec(
        "updated_at",
        "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
        "timestamp",
        False,
        "CURRENT_TIMESTAMP",
    ),
)

PHOTO_ITEM_COLUMNS = (
    ColumnSpec("id", "INT AUTO_INCREMENT PRIMARY KEY COMMENT '照片 ID'", "int", False, None, "照片 ID"),
    _required_int("activity_id", "所属活动 ID"),
    _required_text("title", 160, "照片标题"),
    _required_text("image_url", 600, "照片 URL"),
    ColumnSpec("sort_order", "INT NOT NULL DEFAULT 0 COMMENT '活动内排序'", "int", False, "0", "活动内排序"),
    ColumnSpec("created_at", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP", "timestamp", False, "CURRENT_TIMESTAMP"),
)


TABLE_SPECS: tuple[TableSpec, ...] = (
    TableSpec(
        name="users",
        columns=USERS_COLUMNS,
        indexes=(
            IndexSpec("PRIMARY", "ALTER TABLE users ADD PRIMARY KEY (id)"),
            IndexSpec("uq_users_username", "ALTER TABLE users ADD UNIQUE KEY uq_users_username (username)"),
            IndexSpec("idx_users_role", "CREATE INDEX idx_users_role ON users (role)"),
            IndexSpec("idx_users_active", "CREATE INDEX idx_users_active ON users (is_active)"),
        ),
        create_sql="""
            CREATE TABLE users (
              id INT AUTO_INCREMENT PRIMARY KEY COMMENT '用户 ID',
              username VARCHAR(32) NOT NULL COMMENT '昵称/登录用户名',
              password_hash VARCHAR(255) NOT NULL COMMENT 'PBKDF2 密码哈希',
              display_name VARCHAR(80) DEFAULT NULL COMMENT '姓名',
              role ENUM('admin', 'user') NOT NULL DEFAULT 'user' COMMENT '用户角色：admin 管理员，user 普通用户',
              is_active TINYINT(1) NOT NULL DEFAULT 1 COMMENT '账号是否启用',
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_users_username (username),
              INDEX idx_users_role (role),
              INDEX idx_users_active (is_active)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
    ),
    TableSpec(
        name="projects",
        columns=PROJECTS_COLUMNS,
        indexes=(
            IndexSpec("PRIMARY", "ALTER TABLE projects ADD PRIMARY KEY (id)"),
            IndexSpec("idx_category", "CREATE INDEX idx_category ON projects (category)"),
            IndexSpec("idx_year", "CREATE INDEX idx_year ON projects (year)"),
            IndexSpec("idx_popularity", "CREATE INDEX idx_popularity ON projects (popularity)"),
        ),
        create_sql="""
            CREATE TABLE projects (
              id INT AUTO_INCREMENT PRIMARY KEY COMMENT '项目 ID',
              name VARCHAR(120) NOT NULL COMMENT '项目名称',
              leader VARCHAR(80) NOT NULL COMMENT '负责人',
              members TEXT NOT NULL COMMENT '项目成员，可用逗号分隔或 JSON 字符串',
              category VARCHAR(60) NOT NULL COMMENT '分类，例如 科技创新/公益服务/艺术设计',
              year INT NOT NULL COMMENT '项目年份',
              icon VARCHAR(255) DEFAULT NULL COMMENT '项目图标图片 URL',
              description TEXT NOT NULL COMMENT '简要介绍/完整简介',
              media JSON DEFAULT NULL COMMENT '照片/视频链接数组，JSON 格式',
              cas_creativity TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否包含 Creativity',
              cas_activity TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否包含 Activity',
              cas_service TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否包含 Service',
              popularity INT NOT NULL DEFAULT 0 COMMENT '热度，用于推荐排序',
              updates JSON DEFAULT NULL COMMENT '项目动态数组，JSON 格式',
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              INDEX idx_category (category),
              INDEX idx_year (year),
              INDEX idx_popularity (popularity)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
    ),
    TableSpec(
        name="project_categories",
        columns=PROJECT_CATEGORY_COLUMNS,
        indexes=(
            IndexSpec("PRIMARY", "ALTER TABLE project_categories ADD PRIMARY KEY (id)"),
            IndexSpec("uq_project_categories_name", "ALTER TABLE project_categories ADD UNIQUE KEY uq_project_categories_name (name)"),
            IndexSpec("idx_project_categories_sort", "CREATE INDEX idx_project_categories_sort ON project_categories (is_active, sort_order, id)"),
        ),
        create_sql="""
            CREATE TABLE project_categories (
              id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'CAS 项目分类 ID',
              name VARCHAR(60) NOT NULL COMMENT 'CAS 项目分类名称',
              sort_order INT NOT NULL DEFAULT 0 COMMENT '人工排序权重，数字越小越靠前',
              is_active TINYINT(1) NOT NULL DEFAULT 1 COMMENT '分类是否启用',
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_project_categories_name (name),
              INDEX idx_project_categories_sort (is_active, sort_order, id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
    ),
    TableSpec(
        name="resource_categories",
        columns=RESOURCE_CATEGORY_COLUMNS,
        indexes=(
            IndexSpec("PRIMARY", "ALTER TABLE resource_categories ADD PRIMARY KEY (id)"),
            IndexSpec("uq_resource_categories_value", "ALTER TABLE resource_categories ADD UNIQUE KEY uq_resource_categories_value (value)"),
            IndexSpec("idx_resource_categories_sort", "CREATE INDEX idx_resource_categories_sort ON resource_categories (is_active, sort_order, id)"),
        ),
        create_sql="""
            CREATE TABLE resource_categories (
              id INT AUTO_INCREMENT PRIMARY KEY COMMENT '资源分类 ID',
              value VARCHAR(40) NOT NULL COMMENT '资源分类入口值，例如 yearbook/photos/other；photos 只作为活动照片入口',
              label VARCHAR(60) NOT NULL COMMENT '资源分类展示名称',
              sort_order INT NOT NULL DEFAULT 0 COMMENT '人工排序权重，数字越小越靠前',
              is_active TINYINT(1) NOT NULL DEFAULT 1 COMMENT '分类是否启用',
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_resource_categories_value (value),
              INDEX idx_resource_categories_sort (is_active, sort_order, id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
    ),
    TableSpec(
        name="resources",
        columns=RESOURCES_COLUMNS,
        indexes=(
            IndexSpec("PRIMARY", "ALTER TABLE resources ADD PRIMARY KEY (id)"),
            IndexSpec("idx_resource_category", "CREATE INDEX idx_resource_category ON resources (category)"),
            IndexSpec("idx_resource_year", "CREATE INDEX idx_resource_year ON resources (year)"),
            IndexSpec("idx_resource_hot", "CREATE INDEX idx_resource_hot ON resources (hot)"),
            IndexSpec("idx_resource_downloads", "CREATE INDEX idx_resource_downloads ON resources (downloads)"),
        ),
        create_sql="""
            CREATE TABLE resources (
              id INT AUTO_INCREMENT PRIMARY KEY COMMENT '资源 ID',
              title VARCHAR(160) NOT NULL COMMENT '资源标题',
              description TEXT COMMENT '资源简介',
              year INT NOT NULL COMMENT '资源年份',
              category VARCHAR(40) NOT NULL COMMENT '普通资源分类值，例如 yearbook/other；活动照片不写入 resources',
              label VARCHAR(60) NOT NULL COMMENT '资源分类展示名',
              hot INT NOT NULL DEFAULT 0 COMMENT '热度',
              downloads INT NOT NULL DEFAULT 0 COMMENT '下载次数',
              image VARCHAR(600) NOT NULL COMMENT '封面图片 URL',
              resource_url VARCHAR(600) NOT NULL COMMENT '资源访问或下载 URL',
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              INDEX idx_resource_category (category),
              INDEX idx_resource_year (year),
              INDEX idx_resource_hot (hot),
              INDEX idx_resource_downloads (downloads)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
    ),
    TableSpec(
        name="photo_activities",
        columns=PHOTO_ACTIVITY_COLUMNS,
        indexes=(
            IndexSpec("PRIMARY", "ALTER TABLE photo_activities ADD PRIMARY KEY (id)"),
            IndexSpec("idx_photo_activity_year", "CREATE INDEX idx_photo_activity_year ON photo_activities (year)"),
            IndexSpec("idx_photo_activity_hot", "CREATE INDEX idx_photo_activity_hot ON photo_activities (hot)"),
            IndexSpec("idx_photo_activity_downloads", "CREATE INDEX idx_photo_activity_downloads ON photo_activities (downloads)"),
            IndexSpec("idx_photo_activity_sort", "CREATE INDEX idx_photo_activity_sort ON photo_activities (sort_order, id)"),
        ),
        create_sql="""
            CREATE TABLE photo_activities (
              id INT AUTO_INCREMENT PRIMARY KEY COMMENT '活动 ID',
              activity VARCHAR(160) NOT NULL COMMENT '活动名称',
              description TEXT NOT NULL COMMENT '活动照片简介',
              year INT NOT NULL COMMENT '活动年份',
              hot INT NOT NULL DEFAULT 0 COMMENT '活动热度',
              downloads INT NOT NULL DEFAULT 0 COMMENT '下载次数',
              sort_order INT NOT NULL DEFAULT 0 COMMENT '人工排序权重，数字越小越靠前',
              photo_dir VARCHAR(600) DEFAULT NULL COMMENT '活动照片目录 URL，指向 public 下的文件夹',
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              INDEX idx_photo_activity_year (year),
              INDEX idx_photo_activity_hot (hot),
              INDEX idx_photo_activity_downloads (downloads),
              INDEX idx_photo_activity_sort (sort_order, id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
    ),
    TableSpec(
        name="photo_items",
        columns=PHOTO_ITEM_COLUMNS,
        indexes=(
            IndexSpec("PRIMARY", "ALTER TABLE photo_items ADD PRIMARY KEY (id)"),
            IndexSpec("idx_photo_items_activity", "CREATE INDEX idx_photo_items_activity ON photo_items (activity_id, sort_order)"),
        ),
        create_sql="""
            CREATE TABLE photo_items (
              id INT AUTO_INCREMENT PRIMARY KEY COMMENT '照片 ID',
              activity_id INT NOT NULL COMMENT '所属活动 ID',
              title VARCHAR(160) NOT NULL COMMENT '照片标题',
              image_url VARCHAR(600) NOT NULL COMMENT '照片 URL',
              sort_order INT NOT NULL DEFAULT 0 COMMENT '活动内排序',
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              CONSTRAINT fk_photo_items_activity
                FOREIGN KEY (activity_id) REFERENCES photo_activities(id)
                ON DELETE CASCADE,
              INDEX idx_photo_items_activity (activity_id, sort_order)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
    ),
)

FOREIGN_KEY_SPECS = (
    ForeignKeySpec(
        name="fk_photo_items_activity",
        table="photo_items",
        column="activity_id",
        referenced_table="photo_activities",
        referenced_column="id",
        sql="""
            ALTER TABLE photo_items
              ADD CONSTRAINT fk_photo_items_activity
              FOREIGN KEY (activity_id) REFERENCES photo_activities(id)
              ON DELETE CASCADE
        """,
    ),
)


def _empty_result() -> dict[str, Any]:
    return {
        "ok": True,
        "createdTables": [],
        "addedColumns": [],
        "addedIndexes": [],
        "addedConstraints": [],
        "warnings": [],
        "errors": [],
    }


def _position_sql(previous_column: str | None) -> str:
    return f" AFTER {previous_column}" if previous_column else " FIRST"


def _execute_ddl(cursor: Any, sql: str, errors: list[str], label: str) -> bool:
    try:
        cursor.execute(sql)
        return True
    except MySQLError as exc:
        errors.append(f"{label} 失败：{exc}")
        return False


def _table_exists(cursor: Any, table: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
        """,
        (table,),
    )
    return cursor.fetchone()["count"] > 0


def _columns(cursor: Any, table: str) -> dict[str, dict[str, Any]]:
    cursor.execute(
        """
        SELECT
          COLUMN_NAME,
          COLUMN_TYPE,
          IS_NULLABLE,
          COLUMN_DEFAULT,
          COLUMN_COMMENT
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
        """,
        (table,),
    )
    return {row["COLUMN_NAME"]: row for row in cursor.fetchall()}


def _index_exists(cursor: Any, table: str, index_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND INDEX_NAME = %s
        """,
        (table, index_name),
    )
    return cursor.fetchone()["count"] > 0


def _foreign_key_exists(cursor: Any, constraint_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.REFERENTIAL_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA = DATABASE()
          AND CONSTRAINT_NAME = %s
        """,
        (constraint_name,),
    )
    return cursor.fetchone()["count"] > 0


def _same_foreign_key_exists(cursor: Any, spec: ForeignKeySpec) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
          AND REFERENCED_TABLE_NAME = %s
          AND REFERENCED_COLUMN_NAME = %s
        """,
        (spec.table, spec.column, spec.referenced_table, spec.referenced_column),
    )
    return cursor.fetchone()["count"] > 0


def _normalize_default(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip("'").lower()
    if normalized == "current_timestamp()":
        return "current_timestamp"
    return normalized


def _warn_column_mismatches(
    table: str,
    spec: ColumnSpec,
    actual: dict[str, Any],
    warnings: list[str],
) -> None:
    actual_type = str(actual["COLUMN_TYPE"]).lower().replace(" ", "")
    expected_type = spec.column_type.lower().replace(" ", "")
    if actual_type != expected_type:
        warnings.append(f"{table}.{spec.name} 类型为 {actual['COLUMN_TYPE']}，期望 {spec.column_type}；未自动修改。")

    actual_nullable = actual["IS_NULLABLE"] == "YES"
    if actual_nullable != spec.nullable:
        expected_nullable = "YES" if spec.nullable else "NO"
        warnings.append(f"{table}.{spec.name} 可空性为 {actual['IS_NULLABLE']}，期望 {expected_nullable}；未自动修改。")

    expected_default = _normalize_default(spec.default)
    actual_default = _normalize_default(actual["COLUMN_DEFAULT"])
    if expected_default != actual_default:
        warnings.append(f"{table}.{spec.name} 默认值为 {actual['COLUMN_DEFAULT']!r}，期望 {spec.default!r}；未自动修改。")

    if spec.comment and str(actual.get("COLUMN_COMMENT") or "") != spec.comment:
        warnings.append(f"{table}.{spec.name} 注释与规格不一致；未自动修改。")


def _add_missing_column(
    cursor: Any,
    table: str,
    column: ColumnSpec,
    previous_column: str | None,
    result: dict[str, Any],
) -> bool:
    position = _position_sql(previous_column)
    if column.safe_definition and column.placeholder_sql is not None:
        add_sql = f"ALTER TABLE {table} ADD COLUMN {column.name} {column.safe_definition}{position}"
        if not _execute_ddl(cursor, add_sql, result["errors"], f"新增字段 {table}.{column.name}"):
            return False
        cursor.execute(f"UPDATE {table} SET {column.name} = {column.placeholder_sql} WHERE {column.name} IS NULL")
        modify_sql = f"ALTER TABLE {table} MODIFY COLUMN {column.name} {column.definition}{position}"
        if not _execute_ddl(cursor, modify_sql, result["errors"], f"恢复字段约束 {table}.{column.name}"):
            return False
    else:
        add_sql = f"ALTER TABLE {table} ADD COLUMN {column.name} {column.definition}{position}"
        if not _execute_ddl(cursor, add_sql, result["errors"], f"新增字段 {table}.{column.name}"):
            return False

    result["addedColumns"].append(f"{table}.{column.name}")
    return True


def _repair_table(cursor: Any, table: TableSpec, result: dict[str, Any]) -> None:
    if not _table_exists(cursor, table.name):
        if _execute_ddl(cursor, table.create_sql, result["errors"], f"创建表 {table.name}"):
            result["createdTables"].append(table.name)
        return

    existing_columns = _columns(cursor, table.name)
    previous_column: str | None = None
    for column in table.columns:
        if column.name in existing_columns:
            _warn_column_mismatches(table.name, column, existing_columns[column.name], result["warnings"])
            previous_column = column.name
            continue
        if _add_missing_column(cursor, table.name, column, previous_column, result):
            previous_column = column.name

    for index in table.indexes:
        if _index_exists(cursor, table.name, index.name):
            continue
        if _execute_ddl(cursor, index.sql, result["errors"], f"新增索引 {table.name}.{index.name}"):
            result["addedIndexes"].append(f"{table.name}.{index.name}")


def _repair_foreign_keys(cursor: Any, result: dict[str, Any]) -> None:
    for spec in FOREIGN_KEY_SPECS:
        if not _table_exists(cursor, spec.table) or not _table_exists(cursor, spec.referenced_table):
            result["warnings"].append(f"{spec.name} 依赖表不存在，已跳过外键检查。")
            continue
        if _foreign_key_exists(cursor, spec.name):
            continue
        if _same_foreign_key_exists(cursor, spec):
            result["warnings"].append(f"{spec.table}.{spec.column} 已存在同等外键，但名称不是 {spec.name}；未重复创建。")
            continue
        if _execute_ddl(cursor, spec.sql, result["errors"], f"新增外键 {spec.name}"):
            result["addedConstraints"].append(spec.name)


def repair_database_schema() -> dict[str, Any]:
    """Repair missing admin-approved schema elements and return a compact report."""

    result = _empty_result()
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            for table in TABLE_SPECS:
                _repair_table(cursor, table, result)
            _repair_foreign_keys(cursor, result)

    result["ok"] = not result["errors"]
    return result
