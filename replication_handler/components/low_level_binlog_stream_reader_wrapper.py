# -*- coding: utf-8 -*-
import logging

from pymysqlreplication import BinLogStreamReader
from pymysqlreplication.event import GtidEvent
from pymysqlreplication.event import QueryEvent
from pymysqlreplication.row_event import UpdateRowsEvent
from pymysqlreplication.row_event import WriteRowsEvent
from pymysqlreplication.constants.BINLOG import WRITE_ROWS_EVENT_V2
from pymysqlreplication.constants.BINLOG import UPDATE_ROWS_EVENT_V2
from pymysqlreplication.constants.BINLOG import DELETE_ROWS_EVENT_V2

from replication_handler import config
from replication_handler.components.base_binlog_stream_reader_wrapper import BaseBinlogStreamReaderWrapper
from replication_handler.components.stubs.stub_dp_clientlib import MessageType
from replication_handler.util.misc import DataEvent


log = logging.getLogger('replication_handler.components.low_level_binlog_stream_reader_wrapper')


event_type_map = {
    WRITE_ROWS_EVENT_V2: MessageType.create,
    UPDATE_ROWS_EVENT_V2: MessageType.update,
    DELETE_ROWS_EVENT_V2: MessageType.delete,
}


class LowLevelBinlogStreamReaderWrapper(BaseBinlogStreamReaderWrapper):
    """ This class wraps pymysqlreplication stream object, providing the ability to
    resume stream at a specific position, peek at next event, and pop next event.

    Args:
      position(Position object): use to specify where the stream should resume.
    """

    def __init__(self, position):
        super(LowLevelBinlogStreamReaderWrapper, self).__init__()
        source_config = config.source_database_config.entries[0]
        connection_config = {
            'host': source_config['host'],
            'port': source_config['port'],
            'user': source_config['user'],
            'passwd': source_config['passwd']
        }
        allowed_event_types = [
            GtidEvent,
            QueryEvent,
            WriteRowsEvent,
            UpdateRowsEvent
        ]

        self._seek(connection_config, allowed_event_types, position)

    def _refill_current_events_if_empty(self):
        if not self.current_events:
            self.current_events.extend(self._prepare_event(self.stream.fetchone()))

    def _prepare_event(self, event):
        if isinstance(event, (QueryEvent, GtidEvent)):
            # TODO(cheng|DATAPIPE-173): log_pos and log_file is useful information
            # to have on events, we will decide if we want to remove this when gtid is
            # enabled if the future.
            event.log_pos = self.stream.log_pos
            event.log_file = self.stream.log_file
            return [event]
        else:
            return self._get_data_events_from_row_event(event)

    def _get_data_events_from_row_event(self, row_event):
        """ Convert the rows into events."""
        return [
            DataEvent(
                schema=row_event.schema,
                table=row_event.table,
                log_pos=self.stream.log_pos,
                log_file=self.stream.log_file,
                row=row,
                event_type=event_type_map[row_event.event_type]
            ) for row in row_event.rows
        ]

    def _seek(self, connection_config, allowed_event_types, position):
        # server_id doesn't seem to matter but must be set.
        # blocking=True will will make stream iterate infinitely.
        self.stream = BinLogStreamReader(
            connection_settings=connection_config,
            server_id=1,
            blocking=True,
            only_events=allowed_event_types,
            **position.to_replication_dict()
        )
