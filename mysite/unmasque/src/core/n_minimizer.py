from ...refactored.abstract.MinimizerBase import Minimizer
from ...refactored.util.common_queries import alter_table_rename_to, get_restore_name, drop_view, \
    create_view_as_select_star_where_ctid
from ...refactored.util.utils import isQ_result_empty


def is_less_than(x, end_ctid):
    ex = x[1:-1]
    ec = end_ctid[1:-1]
    exes = ex.split(',')
    eces = ec.split(',')
    return int(exes[0]) < int(eces[0]) and int(exes[1]) < int(eces[1])


def get_one_less(ctid):
    po = ctid[1:-1]
    idx = po.split(',')
    if int(idx[1]) > 1:
        less_one = str(int(idx[1]) - 1)
        return f"({idx[0], less_one})"
    return None


def format_ctid(ctid):
    ctid = ctid[1:-1]
    ctid = ctid.replace("\'", "")
    return ctid


class NMinimizer(Minimizer):
    SWTICH_TRANSACTION_ON = 2000

    def __init__(self, connectionHelper,
                 core_relations, core_sizes):
        super().__init__(connectionHelper, core_relations, core_sizes, "N_Minimizer")
        self.core_sizes = core_sizes
        self.may_exclude = {}
        self.must_include = {}
        self.view_drop_count = 0

    def is_ok_without_tuple(self, tabname, query):
        exclude_ctids = ""
        for x in self.may_exclude[tabname]:
            exclude_ctids += f" and ctid != '(0,{str(x)})'"

        end_ctid_idx = self.must_include[tabname][-1]
        start_ctid = "(0,1)"
        end_ctid = f"(0,{str(end_ctid_idx)})"
        create_cmd = f"Create view {tabname} as Select * From {get_restore_name(tabname)} " \
                     f"Where ctid >= '{start_ctid}' and ctid <= '{end_ctid}' {exclude_ctids} ;"
        self.logger.debug(create_cmd)
        self.connectionHelper.execute_sql([create_cmd])
        self.logger.debug("end_ctid_idx", end_ctid_idx)

        if self.sanity_check(query):
            if len(self.must_include[tabname]) > 1:
                em = self.must_include[tabname][-2]
                self.may_exclude[tabname].append(em)
                self.must_include[tabname].remove(em)
            return True
        else:
            self.logger.debug("end_ctid_idx", end_ctid_idx)
        return False

    def doActualJob(self, args):
        query = self.extract_params_from_args(args)
        for tab in self.core_relations:
            self.minimize_one_relation(query, tab)
        return True

    def minimize_one_relation(self, query, tab):
        size = self.core_sizes[tab]
        self.may_exclude[tab] = []  # set of tuples that can be removed for getting non empty result
        self.must_include[tab] = []  # set of tuples that can be removed for getting non empty result
        self.connectionHelper.execute_sql([alter_table_rename_to(tab, get_restore_name(tab))])
        ok = True
        for row in range(self.core_sizes[tab]):
            if ok:
                self.must_include[tab].append(size - row)
            else:
                self.may_exclude[tab].append(self.must_include[tab].pop())
            self.connectionHelper.execute_sql([drop_view(tab)])
            ok = self.is_ok_without_tuple(tab, query)
            self.logger.debug(self.may_exclude[tab])
            self.logger.debug(self.must_include[tab])
        self.core_sizes[tab] = len(self.must_include[tab])

    def minimize_one_relation1(self, query, tab):
        sctid = '(0,1)'
        ectid = self.connectionHelper.execute_sql_fetchone_0("Select MAX(ctid) from " + f"{tab};")
        end_ctid, start_ctid = self.try_binary_halving(query, tab)
        while sctid != start_ctid or ectid != end_ctid:
            self.core_sizes = self.update_with_remaining_size(self.core_sizes,
                                                              end_ctid,
                                                              start_ctid, tab, get_restore_name(tab))
            sctid = start_ctid
            ectid = end_ctid
            end_ctid, start_ctid = self.try_binary_halving(query, tab)

        self.may_exclude[tab] = []  # set of tuples that can be removed for getting non empty result
        self.must_include[tab] = []  # set of tuples that can be removed for getting non empty result

        # first time

        self.may_exclude[tab].append(end_ctid)

        c2tid = self.connectionHelper.execute_sql_fetchone_0("SELECT MAX(ctid) FROM " +
                                                             f"{tab}" + " WHERE ctid < " + f"{end_ctid});")
        self.logger.debug(c2tid)
        self.must_include[tab].append(c2tid)

        # self.connectionHelper.execute_sql([alter_table_rename_to(tab, get_restore_name(tab))])
        ok = True
        while ok:
            self.connectionHelper.execute_sql([drop_view(tab)])
            self.swicth_transaction(tab)
            ok = self.is_ok_without_tuple1(tab, query, start_ctid)
            self.logger.debug(self.may_exclude[tab])
            self.logger.debug(self.must_include[tab])
        self.core_sizes[tab] = len(self.must_include[tab])

    def is_ok_without_tuple1(self, tab, query, start_ctid):
        end_ctid = self.must_include[tab][-1]

        exclude_ctids = ""
        for x in self.may_exclude[tab]:
            if is_less_than(x, end_ctid):
                exclude_ctids += f" and ctid != '{x})'"

        create_cmd = f"Create view {tab} as Select * From {get_restore_name(tab)} " \
                     f"Where ctid >= '{start_ctid}' and ctid <= '{end_ctid}' {exclude_ctids} ;"
        self.logger.debug(create_cmd)
        self.connectionHelper.execute_sql([create_cmd])
        if self.sanity_check(query):
            self.may_exclude[tab].pop()
            self.may_exclude[tab].append(self.must_include[tab].pop())
            nctid = get_one_less(end_ctid)
            if nctid is None:
                nctid = self.connectionHelper.execute_sql_fetchone_0("Select MAX(ctid) from "
                                                                     + f"{get_restore_name(tab)} Where ctid < '"
                                                                     + f"{end_ctid}';")
            else:
                nctid = format_ctid(nctid)
            self.must_include[tab].append(nctid)
            return True
        else:
            self.must_include[tab].append(self.may_exclude[tab].pop())
        return False

    '''
    Database has a limit on maximum number of locks per transaction.
    Experimentally it was found ~2500+ for Postgres running locally.
    too many object creation/drop causes acquiring lock too many times, causing shared memory to go out of limit.
    Hence, switching transaction.
    '''

    def swicth_transaction(self, tab):
        self.view_drop_count += 1
        self.logger.debug(self.view_drop_count)
        if self.view_drop_count >= self.SWTICH_TRANSACTION_ON:
            self.connectionHelper.closeConnection()
            self.connectionHelper.connectUsingParams()
            self.connectionHelper.execute_sql([alter_table_rename_to(tab, get_restore_name(tab))])
            self.view_drop_count = 0

    def try_binary_halving(self, query, tab):
        return self.get_start_and_end_ctids(self.core_sizes, query, tab, get_restore_name(tab))

    def calculate_mid_ctids(self, start_page, end_page, size):
        mid_page = int((start_page + end_page) / 2)
        mid_ctid1 = "(" + str(mid_page) + ",1)"
        mid_ctid2 = "(" + str(mid_page) + ",2)"
        return mid_ctid1, mid_ctid2

    def create_view_execute_app_drop_view(self,
                                          end_ctid,
                                          mid_ctid1,
                                          mid_ctid2,
                                          query,
                                          start_ctid,
                                          tabname,
                                          tabname1):
        if self.check_result_for_half(start_ctid, mid_ctid1, tabname1, tabname, query):
            # Take the upper half
            end_ctid = mid_ctid1
        elif self.check_result_for_half(mid_ctid2, end_ctid, tabname1, tabname, query):
            # Take the lower half
            start_ctid = mid_ctid2
        self.connectionHelper.execute_sql([drop_view(tabname)])
        return end_ctid, start_ctid
