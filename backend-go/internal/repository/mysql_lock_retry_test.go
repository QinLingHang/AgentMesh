package repository

import (
	"errors"
	"testing"

	mysqlDriver "github.com/go-sql-driver/mysql"
)

func TestIsRetryableMySQLLockError(t *testing.T) {
	tests := []struct {
		name string
		err  error
		want bool
	}{
		{name: "lock wait timeout", err: &mysqlDriver.MySQLError{Number: 1205}, want: true},
		{name: "deadlock", err: &mysqlDriver.MySQLError{Number: 1213}, want: true},
		{name: "serialization sqlstate", err: &mysqlDriver.MySQLError{Number: 9999, SQLState: [5]byte{'4', '0', '0', '0', '1'}}, want: true},
		{name: "wrapped", err: errors.Join(errors.New("topology"), &mysqlDriver.MySQLError{Number: 1213}), want: true},
		{name: "non transient mysql", err: &mysqlDriver.MySQLError{Number: 1062}, want: false},
		{name: "non mysql", err: errors.New("failure"), want: false},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if got := isRetryableMySQLLockError(test.err); got != test.want {
				t.Fatalf("isRetryableMySQLLockError() = %v, want %v", got, test.want)
			}
		})
	}
}
