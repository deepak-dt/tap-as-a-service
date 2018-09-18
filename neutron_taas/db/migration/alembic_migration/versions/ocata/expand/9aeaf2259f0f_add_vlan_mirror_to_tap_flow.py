"""add_vlan_mirror_to_tap_flow

Revision ID: 9aeaf2259f0f
Revises: fddbdec8711a
Create Date: 2018-09-18 17:02:41.226135

"""

# revision identifiers, used by Alembic.
revision = '9aeaf2259f0f'
down_revision = 'fddbdec8711a'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('tap_flows', sa.Column('vlan_mirror', sa.String(1024),
                                         nullable=True))
