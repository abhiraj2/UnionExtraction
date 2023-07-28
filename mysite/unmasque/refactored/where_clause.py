import copy
import datetime
import math

import psycopg2

from mysite.unmasque.refactored.abstract.ExtractorBase import Base
from mysite.unmasque.refactored.executable import Executable
from mysite.unmasque.refactored.util.utils import is_int, get_all_combo_lists, get_datatype_from_typesList, \
    get_dummy_val_for, get_val_plus_delta, get_min_and_max_val, isQ_result_empty


def get_two_different_vals(list_type):
    datatype = get_datatype_from_typesList(list_type)
    val1 = get_dummy_val_for(datatype)
    val2 = get_val_plus_delta(datatype, val1, 1)
    return val1, val2


def construct_two_lists(attrib_types_dict, curr_list, elt):
    list1 = [curr_list[index] for index in elt]
    list_type = attrib_types_dict[curr_list[elt[0]]] if elt else ''
    list2 = list(set(curr_list) - set(list1))
    return list1, list2, list_type


def get_test_value_for(datatype, val, precision):
    if datatype == 'float' or datatype == 'numeric':
        return round(val, precision)
    elif datatype == 'int':
        return int(val)


def get_constants_for(datatype):
    if datatype == 'int':
        while_cut_off = 0
        delta = 1
    elif datatype == 'float' or datatype == 'numeric':
        while_cut_off = 0.00001
        delta = 0.01
    return delta, while_cut_off


class WhereClause(Base):
    local_other_info_dict = {}
    local_instance_no = 0
    local_instance_list = []

    def __init__(self, connectionHelper,
                 global_key_lists,
                 core_relations,
                 global_other_info_dict,
                 global_result_dict,
                 global_min_instance_dict):
        super().__init__(connectionHelper, "Where_clause")
        self.app = Executable(connectionHelper)

        # from initiator
        self.global_key_lists = global_key_lists

        # from from clause
        self.core_relations = core_relations

        # from view minimizer
        self.global_other_info_dict = global_other_info_dict
        self.global_min_instance_dict = global_min_instance_dict
        self.global_result_dict = global_result_dict

        # init data
        self.global_attrib_types = []
        self.global_all_attribs = []
        self.global_d_plus_value = {}  # this is the tuple from D_min
        self.global_attrib_max_length = {}

        # join data
        self.global_attrib_types_dict = {}
        self.global_attrib_dict = {}

        self.global_join_instance_dict = {}
        self.global_component_dict = {}

        self.global_join_graph = []
        self.global_key_attributes = []

        self.global_instance_dict = {}

    def extract_params_from_args(self, args):
        return args[0]

    def get_join_graph(self, query):
        self.do_init()
        global_key_lists = copy.deepcopy(self.global_key_lists)
        join_graph = []
        attrib_types_dict, combo_dict_of_lists = self.construct_attribs_types_dict()

        # For each list, test its presence in join graph
        # This will either add the list in join graph or break it
        self.global_attrib_dict['join'] = []
        k = 0
        while global_key_lists:
            curr_list = global_key_lists[0]
            join_keys = [join_key for join_key in curr_list if join_key[0] in self.core_relations]
            if len(join_keys) <= 1:
                global_key_lists.remove(curr_list)
                continue
            print("... checking for: ", join_keys)

            k += 1
            self.global_attrib_dict['join'].append("Component-" + str(k))
            self.global_join_instance_dict['Component-' + str(k)] = []
            self.global_component_dict['Component-' + str(k)] = join_keys

            # Try for all possible combinations
            for elt in combo_dict_of_lists[len(join_keys)]:
                self.local_other_info_dict = {}

                list1, list2, list_type = construct_two_lists(attrib_types_dict, join_keys, elt)
                val1, val2 = get_two_different_vals(list_type)
                temp_copy = {tab: self.global_min_instance_dict[tab] for tab in self.core_relations}

                # Assign two different values to two lists in database
                self.assign_values_to_lists(list1, list2, temp_copy, val1, val2)

                self.fill_join_dicts_for_demo(k, list1, list2, temp_copy, val1, val2)

                # CHECK THE RESULT
                new_result = self.app.doJob(query)
                self.global_result_dict['join_' + self.global_attrib_dict['join'][-1] + '_' +
                                        self.global_join_instance_dict['Component-' + str(k)][-1]] = new_result
                self.local_other_info_dict['Result Cardinality'] = len(new_result) - 1
                if len(new_result) > 1:
                    self.remove_edge_from_join_graph_dicts(join_keys, list1, list2, global_key_lists)
                    break

            for keys in global_key_lists:
                if all(x in keys for x in join_keys):
                    global_key_lists.remove(keys)
                    join_graph.append(copy.deepcopy(join_keys))
                    self.local_other_info_dict['Conclusion'] = u'Edge ' + list1[0][1] + u"\u2014" + list2[0][
                        1] + ' is present in the join graph'

            # Assign same values in all cur_lists to get non-empty output
            self.global_other_info_dict['join_' + self.global_attrib_dict['join'][-1] + '_' +
                                        self.global_join_instance_dict['Component-' + str(k)][
                                            -1]] = copy.deepcopy(self.local_other_info_dict)
            for val in join_keys:
                self.connectionHelper.execute_sql(["Insert into " + val[0] + " Select * from " + val[0] + "4;"])

        self.refine_join_graph(join_graph)
        return

    def remove_edge_from_join_graph_dicts(self, curr_list, list1, list2, global_key_lists):
        self.local_other_info_dict[
            'Conclusion'] = 'Selected edge(s) are not present in the join graph'
        for keys in global_key_lists:
            if all(x in keys for x in curr_list):
                global_key_lists.remove(keys)
        global_key_lists.append(copy.deepcopy(list1))
        global_key_lists.append(copy.deepcopy(list2))

    def fill_join_dicts_for_demo(self, k, list1, list2, temp_copy, val1, val2):
        # Hardcoding for demo, need to be revised
        self.global_join_instance_dict['Component-' + str(k)].append(
            u"" + list1[0][1] + u"\u2014" + list2[0][1])
        self.local_other_info_dict['Current Mutation'] = 'Mutation of ' + list1[0][
            1] + ' with value ' + str(val1) + " and " + list2[0][1] + ' with value ' + str(val2)
        for tabname in self.core_relations:
            self.global_min_instance_dict[
                'join_' + self.global_attrib_dict['join'][-1] + '_' + tabname + '_' +
                self.global_join_instance_dict['Component-' + str(k)][-1]] = copy.deepcopy(
                temp_copy[tabname])
        ########################################

    def assign_values_to_lists(self, list1, list2, temp_copy, val1, val2):
        self.assign_value_to_list(list1, temp_copy, val1)
        self.assign_value_to_list(list2, temp_copy, val2)

    def assign_value_to_list(self, list1, temp_copy, val1):
        for val in list1:
            self.connectionHelper.execute_sql(
                ["update " + str(val[0]) + " set " + str(val[1]) + " = " + str(val1) + ";"])
            index = temp_copy[val[0]][0].index(val[1])
            mutated_list = copy.deepcopy(list(temp_copy[val[0]][1]))
            mutated_list[index] = str(val1)
            temp_copy[val[0]][1] = tuple(mutated_list)

    def construct_attribs_types_dict(self):
        max_list_len = max(len(elt) for elt in self.global_key_lists)
        combo_dict_of_lists = get_all_combo_lists(max_list_len)
        attrib_types_dict = {(entry[0], entry[1]): entry[2] for entry in self.global_attrib_types}
        return attrib_types_dict, combo_dict_of_lists

    def refine_join_graph(self, join_graph):
        # refine join graph and get all key attributes
        self.global_join_graph = []
        self.global_key_attributes = []
        for elt in join_graph:
            temp = []
            for val in elt:
                temp.append(val[1])
                self.global_key_attributes.append(val[1])
            self.global_join_graph.append(copy.deepcopy(temp))

    def get_init_data(self):
        if len(self.global_attrib_types) + len(self.global_all_attribs) + len(self.global_d_plus_value) + len(
                self.global_attrib_max_length) == 0:
            self.do_init()

    def do_init(self):
        for tabname in self.core_relations:
            res, desc = self.connectionHelper.execute_sql_fetchall("select column_name, data_type, "
                                                                   "character_maximum_length from "
                                                                   "information_schema.columns "
                                                                   "where table_schema = 'public' and "
                                                                   "table_name = '" + tabname + "';")
            tab_attribs = []
            tab_attribs.extend(row[0] for row in res)
            self.global_all_attribs.append(copy.deepcopy(tab_attribs))

            self.global_attrib_types.extend((tabname, row[0], row[1]) for row in res)

            self.global_attrib_max_length.update(
                {(tabname, row[0]): int(str(row[2])) for row in res if is_int(str(row[2]))})

            res, desc = self.connectionHelper.execute_sql_fetchall("select "
                                                                   + ", ".join(tab_attribs)
                                                                   + " from " + tabname + ";")
            for row in res:
                for attrib, value in zip(tab_attribs, row):
                    self.global_d_plus_value[attrib] = value

    def get_filter_predicates(self, query):
        # query = self.extract_params_from_args(args)

        self.global_attrib_dict['filter'] = []
        self.do_init()

        filter_attribs = []
        total_attribs = 0
        d_plus_value = copy.deepcopy(self.global_d_plus_value)
        attrib_max_length = copy.deepcopy(self.global_attrib_max_length)

        for entry in self.global_attrib_types:
            # attrib_types_dict[(entry[0], entry[1])] = entry[2]
            # aoa change
            self.global_attrib_types_dict[(entry[0], entry[1])] = entry[2]

        for i in range(len(self.core_relations)):
            tabname = self.core_relations[i]
            attrib_list = self.global_all_attribs[i]
            total_attribs = total_attribs + len(attrib_list)
            for attrib in attrib_list:
                if attrib not in self.global_key_attributes:  # filter is allowed only on non-key attribs
                    self.extract_filter_on_attrib(attrib, attrib_max_length, d_plus_value, filter_attribs,
                                                          query, tabname)

                    print("filter_attribs", filter_attribs)
        return filter_attribs

    def extract_filter_on_attrib(self, attrib, attrib_max_length, d_plus_value, filter_attribs, query, tabname):
        self.global_attrib_dict['filter'].append(attrib)
        self.local_other_info_dict = {}
        self.local_instance_no = 1
        self.global_instance_dict[attrib] = []
        self.local_instance_list = []
        if 'int' in self.global_attrib_types_dict[(tabname, attrib)]:
            self.handle_int_filter(attrib, d_plus_value, filter_attribs, tabname, query)
        elif any(x in self.global_attrib_types_dict[(tabname, attrib)] for x in ['text', 'char', 'varbit']):
            self.handle_string_filter(attrib, attrib_max_length, d_plus_value, filter_attribs, tabname, query)
        elif 'date' in self.global_attrib_types_dict[(tabname, attrib)]:
            self.handle_date_filter(attrib, d_plus_value, filter_attribs, tabname)
        elif 'numeric' in self.global_attrib_types_dict[(tabname, attrib)]:
            self.handle_numeric_filter(attrib, d_plus_value, filter_attribs, tabname, query)
        self.global_instance_dict['filter_' + attrib] = copy.deepcopy(self.local_instance_list)

    def checkAttribValueEffect(self, query, tabname, attrib, val):
        self.connectionHelper.execute_sql(["update " + tabname + " set " + attrib + " = " + str(val) + ";"])
        new_result = self.app.doJob(query)
        if isQ_result_empty(new_result):
            # self.connectionHelper.execute_sql(["ROLLBACK"])
            self.revert_filter_changes(tabname)
        self.update_other_data(tabname, attrib, 'int', val, new_result, [])
        if len(new_result) > 1:
            return True
        return False

    # SUPPORT FUNCTIONS FOR FILTER PREDICATES
    def update_other_data(self, tabname, attrib, attrib_type, val, result, other_info_list):
        self.local_other_info_dict = {}
        if 'text' not in attrib_type and other_info_list != []:
            low = str(other_info_list[0])
            mid = str(other_info_list[1])
            high = str(other_info_list[2])
            low_next = str(other_info_list[3])
            high_next = str(other_info_list[4])
            self.local_other_info_dict['Current Search Range'] = '[' + low + ', ' + high + ']'
            self.local_other_info_dict[
                'Current Mutation'] = 'Mutation of attribute ' + attrib + ' with value ' + str(val)
            self.local_other_info_dict['Result Cardinality'] = (len(result) - 1)
            self.local_other_info_dict['New Search Range'] = '[' + low_next + ', ' + high_next + ']'
        else:
            self.local_other_info_dict[
                'Current Mutation'] = 'Mutation of attribute ' + attrib + ' with value ' + str(val)
            self.local_other_info_dict['Result Cardinality'] = str(len(result) - 1)
        temp = copy.deepcopy(self.global_min_instance_dict[tabname])
        index = temp[0].index(attrib)
        mutated_list = copy.deepcopy(list(temp[1]))
        mutated_list[index] = str(val)
        temp[1] = mutated_list
        for tab in self.core_relations:
            self.global_min_instance_dict[
                'filter_' + attrib + '_' + tab + '_D_mut' + str(self.local_instance_no)] = \
                self.global_min_instance_dict[tab]
        self.global_min_instance_dict[
            'filter_' + attrib + '_' + tabname + '_D_mut' + str(self.local_instance_no)] = temp
        self.global_result_dict[
            'filter_' + attrib + '_D_mut' + str(self.local_instance_no)] = copy.deepcopy(result)
        self.local_other_info_dict['Result Cardinality'] = str(len(result) - 1)
        self.local_instance_list.append('D_mut' + str(self.local_instance_no))
        self.global_other_info_dict[
            'filter_' + attrib + '_D_mut' + str(self.local_instance_no)] = copy.deepcopy(
            self.local_other_info_dict)
        self.local_instance_no += 1

    def handle_numeric_filter(self, attrib, d_plus_value, filterAttribs, tabname, query):
        min_val_domain, max_val_domain = get_min_and_max_val('numeric')
        # NUMERIC HANDLING
        # PRECISION TO BE GET FROM SCHEMA GRAPH
        precision = 2
        min_present = self.checkAttribValueEffect(query, tabname, attrib,
                                                  min_val_domain)  # True implies row was still present
        max_present = self.checkAttribValueEffect(query, tabname, attrib,
                                                  max_val_domain)  # True implies row was still present
        # inference based on flag_min and flag_max
        if max_present and min_present:
            self.local_other_info_dict['Conclusion'] = 'No Filter predicate on ' + attrib
        elif not min_present and not max_present:
            print('identifying value for numeric filter(range) attribute..', attrib)
            equalto_flag = self.get_filter_value(query, 'int', tabname, attrib, float(d_plus_value[attrib]) - .01,
                                                 float(d_plus_value[attrib]) + .01, '=')
            if equalto_flag:
                filterAttribs.append(
                    (tabname, attrib, '=', float(d_plus_value[attrib]), float(d_plus_value[attrib])))
            else:
                val1 = self.get_filter_value(query, 'float', tabname, attrib, math.ceil(float(d_plus_value[attrib])),
                                             max_val_domain, '<=')
                val2 = self.get_filter_value(query, 'float', tabname, attrib, min_val_domain,
                                             math.floor(float(d_plus_value[attrib])), '>=')
                filterAttribs.append((tabname, attrib, 'range', float(val2), float(val1)))
        elif min_present and not max_present:
            print('identifying value for Int filter attribute', attrib)
            val = self.get_filter_value(query, 'float', tabname, attrib, math.ceil(float(d_plus_value[attrib])) - 5,
                                        max_val_domain, '<=')
            val = float(val)
            val1 = self.get_filter_value(query, 'float', tabname, attrib, val, val + 0.99, '<=')
            filterAttribs.append((tabname, attrib, '<=', float(min_val_domain), float(round(val1, 2))))
        elif not min_present and max_present:
            print('identifying value for Int filter attribute', attrib)
            val = self.get_filter_value(query, 'float', tabname, attrib, min_val_domain,
                                        math.floor(float(d_plus_value[attrib]) + 5), '>=')
            val = float(val)
            val1 = self.get_filter_value(query, 'float', tabname, attrib, val - 1, val, '>=')
            filterAttribs.append((tabname, attrib, '>=', float(round(val1, 2)), float(max_val_domain)))

    def get_filter_value(self, query, datatype,
                         tabname, filter_attrib,
                         min_val, max_val, operator):
        query_front = "update " + str(tabname) + " set " + str(filter_attrib) + " = "
        query_back = ";"
        delta, while_cut_off = get_constants_for(datatype)

        # if operator == "<=":
        #    delta = -1 * delta

        self.revert_filter_changes(tabname)

        low = min_val
        high = max_val

        if operator == '<=':
            while (high - low) > while_cut_off:
                mid_val, new_result = self.run_app_with_mid_val(datatype, high, low, query, query_front, query_back)
                if isQ_result_empty(new_result):
                    # put filter_
                    self.update_other_data(tabname, filter_attrib, datatype, mid_val, new_result,
                                           [low, mid_val, high, low, mid_val - delta])
                    high = mid_val - delta
                else:
                    # put filter_
                    self.update_other_data(tabname, filter_attrib, datatype, mid_val, new_result,
                                           [low, mid_val, high, mid_val, high])
                    low = mid_val
                self.revert_filter_changes(tabname)
            return low

        if operator == '>=':
            while (high - low) > while_cut_off:
                mid_val, new_result = self.run_app_with_mid_val(datatype, high, low, query, query_front, query_back)
                if isQ_result_empty(new_result):
                    # put filter_
                    self.update_other_data(tabname, filter_attrib, datatype, mid_val, new_result,
                                           [low, mid_val, high, mid_val + delta, high])
                    low = mid_val + delta
                else:
                    # put filter_
                    self.update_other_data(tabname, filter_attrib, datatype, mid_val, new_result,
                                           [low, mid_val, high, low, mid_val])
                    high = mid_val
                self.revert_filter_changes(tabname)
            return high

        else:  # =, i.e. datatype == 'int'
            is_low = True
            is_high = True
            # updatequery
            is_low = self.run_app_for_a_val(datatype, filter_attrib, is_low,
                                            low, query, query_back, query_front,
                                            tabname)
            is_high = self.run_app_for_a_val(datatype, filter_attrib, is_high,
                                             high, query, query_back, query_front,
                                             tabname)
            self.revert_filter_changes(tabname)
            return not is_low and not is_high

    def run_app_for_a_val(self, datatype, filter_attrib, is_low, low, query, query_back, query_front, tabname):
        low_query = query_front + " " + str(low) + " " + query_back + ";"
        self.connectionHelper.execute_sql([low_query])
        new_result = self.app.doJob(query)
        if len(new_result) <= 1:
            is_low = False
        # put filter_
        self.update_other_data(tabname, filter_attrib, datatype, low, new_result, [])
        return is_low

    def run_app_with_mid_val(self, datatype, high, low, query, q_front, q_back):
        mid_val = (low + high) / 2
        print("[low,high,mid]", low, high, mid_val)
        # updatequery
        update_query = q_front + " " + str(get_test_value_for(datatype, mid_val, 12)) + q_back
        self.connectionHelper.execute_sql([update_query])
        new_result = self.app.doJob(query)
        print(new_result, mid_val)
        return mid_val, new_result

    # mukul
    def handle_date_filter(self, attrib, d_plus_value, filterAttribs, tabname):
        pass
        """

        # min and max domain values (initialize based on data type)
        # PLEASE CONFIRM THAT DATE FORMAT IN DATABASE IS YYYY-MM-DD
        min_val_domain = datetime.date(1, 1, 1)
        max_val_domain = datetime.date(9999, 12, 31)
        flag_min = checkAttribValueEffect(tabname, attrib, "'" + str(
            min_val_domain) + "'")  # True implies row was still present
        flag_max = checkAttribValueEffect(tabname, attrib, "'" + str(
            max_val_domain) + "'")  # True implies row was still present
        # inference based on flag_min and flag_max
        if (flag_max == True and flag_min == True):
            self.local_other_info_dict['Conclusion'] = 'No Filter predicate on ' + attrib
            self.global_other_info_dict[
                'filter_' + attrib + '_D_mut' + str(self.local_instance_no - 1)] = copy.deepcopy(
                self.local_other_info_dict)
        elif (flag_min == False and flag_max == False):
            self.local_other_info_dict[
                'Conclusion'] = 'Filter predicate on ' + attrib + ' with operator between '
            self.global_other_info_dict[
                'filter_' + attrib + '_D_mut' + str(self.local_instance_no - 1)] = copy.deepcopy(
                self.local_other_info_dict)
            print('identifying value for Date filter(range) attribute..', attrib)
            equalto_flag = getDateFilterValue(tabname, attrib,
                                              d_plus_value[attrib] - datetime.timedelta(days=1),
                                              d_plus_value[attrib] + datetime.timedelta(days=1), '=')
            if equalto_flag:
                filterAttribs.append((tabname, attrib, '=', d_plus_value[attrib], d_plus_value[attrib]))
                self.local_other_info_dict[
                    'Conclusion'] = u'Filter Predicate is \u2013 ' + attrib + ' = ' + str(
                    d_plus_value[attrib])
                self.global_other_info_dict['filter_' + attrib + '_D_mut' + str(
                    self.local_instance_no - 1)] = copy.deepcopy(
                    self.local_other_info_dict)
            else:
                val1 = getDateFilterValue(tabname, attrib, d_plus_value[attrib],
                                          max_val_domain - datetime.timedelta(days=1), '<=')
                val2 = getDateFilterValue(tabname, attrib, min_val_domain + datetime.timedelta(days=1),
                                          d_plus_value[attrib], '>=')
                filterAttribs.append((tabname, attrib, 'range', val2, val1))
                self.local_other_info_dict[
                    'Conclusion'] = u'Filter Predicate is \u2013 ' + attrib + ' between ' + str(
                    val2) + ' and ' + str(val1)
                self.global_other_info_dict['filter_' + attrib + '_D_mut' + str(
                    self.local_instance_no - 1)] = copy.deepcopy(
                    self.local_other_info_dict)
        elif (flag_min == True and flag_max == False):
            self.local_other_info_dict[
                'Conclusion'] = 'Filter predicate on ' + attrib + ' with operator <='
            self.global_other_info_dict[
                'filter_' + attrib + '_D_mut' + str(self.local_instance_no - 1)] = copy.deepcopy(
                self.local_other_info_dict)
            print('identifying value for Date filter attribute', attrib)
            val = getDateFilterValue(tabname, attrib, d_plus_value[attrib],
                                     max_val_domain - datetime.timedelta(days=1), '<=')
            filterAttribs.append((tabname, attrib, '<=', min_val_domain, val))
            self.local_other_info_dict[
                'Conclusion'] = u'Filter Predicate is \u2013 ' + attrib + ' <= ' + str(val)
            self.global_other_info_dict[
                'filter_' + attrib + '_D_mut' + str(self.local_instance_no - 1)] = copy.deepcopy(
                self.local_other_info_dict)
        elif (flag_min == False and flag_max == True):
            self.local_other_info_dict[
                'Conclusion'] = 'Filter predicate on ' + attrib + ' with operator >= '
            self.global_other_info_dict[
                'filter_' + attrib + '_D_mut' + str(self.local_instance_no - 1)] = copy.deepcopy(
                self.local_other_info_dict)
            print('identifying value for Date filter attribute', attrib)
            val = getDateFilterValue(tabname, attrib, min_val_domain + datetime.timedelta(days=1),
                                     d_plus_value[attrib], '>=')
            filterAttribs.append((tabname, attrib, '>=', val, max_val_domain))
            self.local_other_info_dict[
                'Conclusion'] = u'Filter Predicate is \u2013 ' + attrib + ' >= ' + str(val)
            self.global_other_info_dict[
                'filter_' + attrib + '_D_mut' + str(self.local_instance_no - 1)] = copy.deepcopy(
                self.local_other_info_dict)
                    """

    def handle_string_filter(self, attrib, attrib_max_length, d_plus_value, filterAttribs, tabname, query):
        # STRING HANDLING
        # ESCAPE CHARACTERS IN STRING REMAINING
        if self.checkStringPredicate(query, tabname, attrib):
            # returns true if there is predicate on this string attribute
            self.local_other_info_dict['Conclusion'] = 'Filter Predicate on ' + attrib
            self.global_other_info_dict[
                'filter_' + attrib + '_D_mut' + str(self.local_instance_no - 1)] = copy.deepcopy(
                self.local_other_info_dict)
            print('identifying value for String filter attribute', attrib)
            representative = str(d_plus_value[attrib])
            max_length = 100000
            if (tabname, attrib) in attrib_max_length.keys():
                max_length = attrib_max_length[(tabname, attrib)]
            val = self.getStrFilterValue(query, tabname, attrib, representative, max_length)
            if '%' in val or '_' in val:
                filterAttribs.append((tabname, attrib, 'LIKE', val, val))
                self.local_other_info_dict[
                    'Conclusion'] = u'Filter Predicate is \u2013 ' + attrib + ' LIKE ' + str(val)
            else:
                self.local_other_info_dict[
                    'Conclusion'] = u'Filter Predicate is \u2013 ' + attrib + ' = ' + str(val)
                filterAttribs.append((tabname, attrib, 'equal', val, val))
            self.global_other_info_dict[
                'filter_' + attrib + '_D_mut' + str(self.local_instance_no - 1)] = copy.deepcopy(
                self.local_other_info_dict)
        else:
            self.local_other_info_dict['Conclusion'] = 'No Filter predicate on ' + attrib
            self.global_other_info_dict[
                'filter_' + attrib + '_D_mut' + str(self.local_instance_no - 1)] = copy.deepcopy(
                self.local_other_info_dict)
        # update table so that result is not empty
        self.revert_filter_changes(tabname)

    def revert_filter_changes(self, tabname):
        self.connectionHelper.execute_sql(["Truncate table " + tabname + ';',
                                           "Insert into " + tabname + " Select * from " + tabname + "4;"])

    def handle_int_filter(self, attrib, d_plus_value, filterAttribs, tabname, query):

        # NUMERIC HANDLING
        # min and max domain values (initialize based on data type)
        min_val_domain, max_val_domain = get_min_and_max_val("int")
        min_present = self.checkAttribValueEffect(query, tabname, attrib,
                                                  min_val_domain)  # True implies row was still present
        max_present = self.checkAttribValueEffect(query, tabname, attrib,
                                                  max_val_domain)  # True implies row was still present
        # inference based on flag_min and flag_max
        if max_present and min_present:
            self.local_other_info_dict['Conclusion'] = 'No filter on attribute ' + attrib
            self.global_other_info_dict[
                'filter_' + attrib + '_D_mut' + str(self.local_instance_no - 1)] = copy.deepcopy(
                self.local_other_info_dict)
        elif not min_present and not max_present:
            print('identifying value for Int filter(range) attribute..', attrib)
            equalto_flag = self.get_filter_value(query, 'int', tabname, attrib, int(d_plus_value[attrib]) - 1,
                                                 int(d_plus_value[attrib]) + 1, '=')
            if equalto_flag:
                filterAttribs.append(
                    (tabname, attrib, '=', int(d_plus_value[attrib]), int(d_plus_value[attrib])))
            else:
                val1 = self.get_filter_value(query, 'int', tabname, attrib, int(d_plus_value[attrib]),
                                             max_val_domain - 1,
                                             '<=')
                val2 = self.get_filter_value(query, 'int', tabname, attrib, min_val_domain + 1,
                                             int(d_plus_value[attrib]),
                                             '>=')
                filterAttribs.append((tabname, attrib, 'range', int(val2), int(val1)))
        elif min_present and not max_present:
            print('identifying value for Int filter attribute', attrib)
            val = self.get_filter_value(query, 'int', tabname, attrib, int(d_plus_value[attrib]), max_val_domain - 1,
                                        '<=')
            filterAttribs.append((tabname, attrib, '<=', int(min_val_domain), int(val)))
        elif not min_present and max_present:
            print('identifying value for Int filter attribute', attrib)
            val = self.get_filter_value(query, 'int', tabname, attrib, min_val_domain + 1, int(d_plus_value[attrib]),
                                        '>=')
            filterAttribs.append((tabname, attrib, '>=', int(val), int(max_val_domain)))

    def checkStringPredicate(self, query, tabname, attrib):
        # updatequery
        if self.global_d_plus_value[attrib] is not None and self.global_d_plus_value[attrib][0] == 'a':
            val = 'b'
        else:
            val = 'a'
        new_result = self.run_updateQ_with_temp_str(attrib, query, tabname, val)
        if isQ_result_empty(new_result):
            self.revert_filter_changes(tabname)
            return True
        new_result = self.run_updateQ_with_temp_str(attrib, query, tabname, "" "")
        if isQ_result_empty(new_result):
            self.revert_filter_changes(tabname)
            return True
        return False

    def getStrFilterValue(self, query, tabname, attrib, representative, max_length):
        index = 0
        output = ""
        # currently inverted exclaimaination is being used assuming it will not be in the string
        # GET minimal string with _
        while index < len(representative):
            temp = list(representative)
            if temp[index] == 'a':
                temp[index] = 'b'
            else:
                temp[index] = 'a'
            temp = ''.join(temp)
            new_result = self.run_updateQ_with_temp_str(attrib, query, tabname, temp)
            if len(new_result) > 1:
                self.local_other_info_dict['Conclusion'] = "'" + representative[
                    index] + "' is a replacement for wildcard character '%' or '_'"
                self.global_other_info_dict[
                    'filter_' + attrib + '_D_mut' + str(self.local_instance_no - 1)] = copy.deepcopy(
                    self.local_other_info_dict)
                temp = copy.deepcopy(representative)
                temp = temp[:index] + temp[index + 1:]
                new_result = self.run_updateQ_with_temp_str(attrib, query, tabname, temp)
                if len(new_result) > 1:
                    self.local_other_info_dict['Conclusion'] = "'" + representative[
                        index] + "' is a replacement from wildcard character '%'"
                    self.global_other_info_dict[
                        'filter_' + attrib + '_D_mut' + str(self.local_instance_no - 1)] = copy.deepcopy(
                        self.local_other_info_dict)
                    representative = representative[:index] + representative[index + 1:]
                else:
                    self.local_other_info_dict['Conclusion'] = "'" + representative[
                        index] + "' is a replacement from wildcard character '_'"
                    self.global_other_info_dict[
                        'filter_' + attrib + '_D_mut' + str(self.local_instance_no - 1)] = copy.deepcopy(
                        self.local_other_info_dict)
                    output = output + "_"
                    representative = list(representative)
                    representative[index] = u"\u00A1"
                    representative = ''.join(representative)
                    index = index + 1
            else:
                self.local_other_info_dict['Conclusion'] = "'" + representative[
                    index] + "' is an intrinsic character in filter value"
                self.global_other_info_dict[
                    'filter_' + attrib + '_D_mut' + str(self.local_instance_no - 1)] = copy.deepcopy(
                    self.local_other_info_dict)
                output = output + representative[index]
                index = index + 1
        if output == '':
            return output
        # GET % positions
        index = 0
        representative = copy.deepcopy(output)
        if len(representative) < max_length:
            output = ""
            while index < len(representative):
                temp = list(representative)
                if temp[index] == 'a':
                    temp.insert(index, 'b')
                else:
                    temp.insert(index, 'a')
                temp = ''.join(temp)
                new_result = self.run_updateQ_with_temp_str(attrib, query, tabname, temp)
                if len(new_result) > 1:
                    output = output + '%'
                output = output + representative[index]
                index = index + 1
            temp = list(representative)
            if temp[index - 1] == 'a':
                temp.append('b')
            else:
                temp.append('a')
            temp = ''.join(temp)
            new_result = self.run_updateQ_with_temp_str(attrib, query, tabname, temp)
            if len(new_result) > 1:
                output = output + '%'
        return output

    def run_updateQ_with_temp_str(self, attrib, query, tabname, temp):
        # updatequery
        up_query = "update " + tabname + " set " + attrib + " = " + "'" + temp + "';"
        self.connectionHelper.execute_sql([up_query])
        new_result = self.app.doJob(query)
        self.update_other_data(tabname, attrib, 'text', temp, new_result, [])
        return new_result

    """


def getDateFilterValue(tabname, attrib, min_val, max_val, operator):
    counter = 0
    query_front = "update " + tabname + " set " + attrib + " = "
    query_back = ""
    firstflag = True
    cur = self.global_conn.cursor()
    cur.execute("Truncate Table " + tabname + ";")
    cur.close()
    cur = self.global_conn.cursor()
    # cur.execute("copy " + tabname + " from " + "'" + self.global_reduced_data_path + tabname + ".csv' " + "delimiter ',' csv header;")
    cur.execute("Insert into " + tabname + " Select * from " + tabname + "4;")
    cur.close()
    if operator == '<=':
        low = min_val
        high = max_val
        while int((high - low).days) > 0:
            mid_val = low + datetime.timedelta(days=int(math.ceil(((high - low).days) / 2)))
            # updatequery
            query = query_front + " '" + str(mid_val) + "' " + query_back + ";"
            cur = self.global_conn.cursor()
            cur.execute(query)
            cur.close()
            new_result = executable_aman.getExecOutput(self)
            if len(new_result) <= 1:
                update_other_data(tabname, attrib, 'int', mid_val, new_result,
                                  [low, mid_val, high, low, mid_val - datetime.timedelta(days=1)])
                high = mid_val - datetime.timedelta(days=1)
            else:
                update_other_data(tabname, attrib, 'int', mid_val, new_result, [low, mid_val, high, mid_val, high])
                low = mid_val
            cur = self.global_conn.cursor()
            cur.execute('TRUNCATE table ' + tabname + ';')
            # cur.execute("copy " + tabname + " from " + "'" + self.global_reduced_data_path + tabname + ".csv' " + "delimiter ',' csv header;")
            cur.execute("Insert into " + tabname + " Select * from " + tabname + "4;")
            cur.close()
        return low
    if operator == '>=':
        low = min_val
        high = max_val
        while int((high - low).days) > 0:
            mid_val = low + datetime.timedelta(days=int(((high - low).days) / 2))
            # updatequery
            query = query_front + " '" + str(mid_val) + "' " + query_back + ";"
            cur = self.global_conn.cursor()
            cur.execute(query)
            cur.close()
            new_result = executable_aman.getExecOutput(self)
            if len(new_result) <= 1:
                update_other_data(tabname, attrib, 'int', mid_val, new_result,
                                  [low, mid_val, high, mid_val + datetime.timedelta(days=1), high])
                low = mid_val + datetime.timedelta(days=1)
            else:
                update_other_data(tabname, attrib, 'int', mid_val, new_result, [low, mid_val, high, low, mid_val])
                high = mid_val
            cur = self.global_conn.cursor()
            cur.execute('TRUNCATE table ' + tabname + ';')
            # cur.execute("copy " + tabname + " from " + "'" + self.global_reduced_data_path + tabname + ".csv' " + "delimiter ',' csv header;")
            cur.execute("Insert into " + tabname + " Select * from " + tabname + "4;")
            cur.close()
        return high
    if operator == '=':
        low = min_val
        high = max_val
        flag_low = True
        flag_high = True
        # updatequery
        query = query_front + " '" + str(low) + "' " + query_back + ";"
        cur = self.global_conn.cursor()
        cur.execute(query)
        cur.close()
        new_result = executable_aman.getExecOutput(self)
        update_other_data(tabname, attrib, 'int', low, new_result, [])
        if len(new_result) <= 1:
            flag_low = False
        query = query_front + " '" + str(high) + "' " + query_back + ";"
        cur = self.global_conn.cursor()
        cur.execute(query)
        cur.close()
        new_result = executable_aman.getExecOutput(self)
        update_other_data(tabname, attrib, 'int', high, new_result, [])
        cur = self.global_conn.cursor()
        cur.execute('TRUNCATE table ' + tabname + ';')
        # cur.execute("copy " + tabname + " from " + "'" + self.global_reduced_data_path + tabname + ".csv' " + "delimiter ',' csv header;")
        cur.execute("Insert into " + tabname + " Select * from " + tabname + "4;")
        cur.close()
        if len(new_result) <= 1:
            flag_high = False
        return (flag_low == False and flag_high == False)
    return False



"""


